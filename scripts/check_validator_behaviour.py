#!/usr/bin/env python3
"""Exercise specification and evidence verifiers with isolated synthetic fixtures.

A successful metadata fixture proves verifier behavior, not application behavior.
No fixture command is executed, and no changes or commits touch the source checkout.
"""

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = (
    ".editorconfig", ".gitignore", "AGENTS.md", "Makefile", "PROJECT.md",
    "README.md", ".env.example", ".dockerignore", "compose.yaml", ".github", "docs", "scripts", "specs",
    "backend", "frontend", "identity_provider", "fixtures", "ops",
)
EXCLUDED = {
    ".git", ".venv", "__pycache__", "node_modules", "private", "artifacts",
    "tmp", "dist", "coverage", "playwright-report", "test-results",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "var", ".DS_Store",
}
LIVE_APPROVALS = (
    "identity-provider", "notification-provider", "all-writers-fenced",
    "all-consumers-enforced", "intended-access-baseline",
    "zero-unexplained-divergence", "durable-manager-policy", "restore-reconciliation",
)
PROOF = b"Synthetic verifier metadata fixture. No Scopegate runtime is certified.\n"
RAW_EVIDENCE = object()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def ignore_private(directory, names):
    excluded = set()
    for name in names:
        path = Path(directory) / name
        private = name in EXCLUDED or path.is_symlink()
        private |= name.startswith(".env") and name != ".env.example"
        private |= path.suffix.lower() in {".pdf", ".docx", ".pyc", ".pyo"}
        if private:
            excluded.add(name)
    return excluded


def git_environment():
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("GIT_"):
            del environment[name]
    environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    return environment


def run(root, arguments):
    return subprocess.run(
        arguments, cwd=root, text=True, capture_output=True, check=False,
        timeout=30, env=git_environment(),
    )


def setup_fixture(destination):
    destination.mkdir()
    for relative in PUBLIC_ROOTS:
        source = ROOT / relative
        if source.is_dir():
            shutil.copytree(source, destination / relative, ignore=ignore_private)
        elif source.is_file() and not source.is_symlink():
            shutil.copy2(source, destination / relative)
    commands = (
        ["git", "init", "--quiet"],
        ["git", "add", "--all"],
        ["git", "-c", "user.name=Verifier fixture", "-c", "user.email=fixture@example.test",
         "-c", f"core.hooksPath={os.devnull}", "-c", "commit.gpgsign=false",
         "commit", "--quiet", "-m", "Synthetic public verifier fixture"],
    )
    for command in commands:
        result = run(destination, command)
        if result.returncode:
            raise RuntimeError(f"Fixture setup failed: {result.stderr.strip()}")
    result = run(destination, ["git", "rev-parse", "HEAD"])
    if result.returncode:
        raise RuntimeError("Fixture revision unavailable")
    (destination / "tmp").mkdir()
    (destination / "tmp/proof.txt").write_bytes(PROOF)
    return result.stdout.strip()


def gate_records(execution, artifact, now, revision):
    gates = [
        {
            "id": gate["id"], "scope": "synthetic", "status": "passed",
            "command": gate["planned_entrypoint"], "exit_code": 0, "revision": revision,
            "started_at": (now - timedelta(minutes=2)).isoformat(),
            "finished_at": (now - timedelta(minutes=1)).isoformat(),
            "environment": {"fixture": "synthetic metadata verifier"},
            "artifacts": [copy.deepcopy(artifact)],
        }
        for gate in execution["runtime_gates"]
    ]
    return gates


def scenario_records(root, execution, artifact):
    scenario_gates = {
        "F01": "G-DATABASE", "F02": "G-IDENTITY", "F03": "G-DOMAIN",
        "F04": "G-IDENTITY", "F05": "G-CONTRACT", "F06": "G-MIGRATION",
        "F07": "G-BROWSER", "F08": "G-RELEASE",
    }
    scenarios = []
    for reference in execution["features"]:
        feature = load(root / reference["path"])
        scenarios.extend(
            {"id": case["id"], "gate_ids": [scenario_gates[feature["id"]]],
             "artifact": copy.deepcopy(artifact)}
            for case in feature["acceptance"]
        )
    return scenarios


def task_records(execution, stage, artifact):
    last = {"local": 12, "pilot": 13, "complete": 14}[stage]
    tasks = [
        {"id": task["id"], "status": "complete", "artifact": copy.deepcopy(artifact),
         "scenario_ids": [sid for sid in task["required_evidence"]
                          if re.fullmatch(r"F\d{2}-AC-\d{2}", sid)]}
        for task in execution["tasks"] if int(task["id"][1:]) <= last
    ]
    return tasks


def approval_records(gates, stage, revision, artifact):
    approvals = []
    if stage != "local":
        next(gate for gate in gates if gate["id"] == "G-IDENTITY")["scope"] = "live"
        names = LIVE_APPROVALS + (("cohort-observation", "legacy-contraction") if stage == "complete" else ())
        approvals = [{"id": name, "owner": "Synthetic fixture owner", "revision": revision,
                      "artifact": copy.deepcopy(artifact)} for name in names]
    return approvals


def make_evidence(root, revision, stage="local"):
    execution = load(root / "specs/execution.json")
    artifact = {"path": "tmp/proof.txt", "sha256": hashlib.sha256(PROOF).hexdigest()}
    gates = gate_records(execution, artifact, datetime.now(timezone.utc), revision)
    return {"schema_version": 1, "revision": revision, "gates": gates,
            "scenarios": scenario_records(root, execution, artifact),
            "tasks": task_records(execution, stage, artifact),
            "live_approvals": approval_records(gates, stage, revision, artifact)}


def json_change(relative, change):
    def mutate(root, evidence):
        path = root / relative
        value = load(path)
        change(value)
        dump(path, value)
    return mutate


def duplicate_json_key(relative, key, value):
    def mutate(root, evidence):
        path = root / relative
        contents = path.read_text(encoding="utf-8")
        prefix = json.dumps(key) + ": " + json.dumps(value) + ","
        path.write_text("{" + prefix + contents[1:], encoding="utf-8")
        if relative == "specs/implementation-evidence.json":
            return RAW_EVIDENCE
    return mutate


def evidence_change(change):
    return lambda root, evidence: change(evidence)


def first_gate_field(field, value):
    return evidence_change(lambda evidence: evidence["gates"][0].__setitem__(field, value))


def stage_evidence(stage):
    def mutate(root, evidence):
        evidence.clear()
        evidence.update(make_evidence(root, run(root, ["git", "rev-parse", "HEAD"]).stdout.strip(), stage))
    return mutate


def compose(*changes):
    def mutate(root, evidence):
        for change in changes:
            change(root, evidence)
    return mutate


def specification_cases():
    specs = [sys.executable, "scripts/check_specs.py"]
    no_change = lambda root, value: None
    spec_cases = [
        ("valid specification package", specs, no_change, 0, "PASS:"),
        ("task dependency cycle", specs, json_change("specs/execution.json",
         lambda value: value["tasks"][0]["depends_on"].append(value["tasks"][0]["id"])), 1, "Task graph: cycle"),
        ("missing written clause", specs, json_change("specs/coverage.json",
         lambda value: value["clauses"].pop()), 1, "all 27 atomic clauses"),
        ("missing concept owner", specs, json_change("specs/standards.json",
         lambda value: value["groups"][0]["concepts"][0].pop("owner")), 1, "missing standard owner"),
        ("contradictory numeric range", specs, json_change("specs/contracts/openapi.json",
         lambda value: value["components"]["schemas"].__setitem__("ImpossibleFixtureRange",
                      {"type": "integer", "minimum": 101, "maximum": 100})), 1, "contradictory numeric bounds"),
        ("duplicate specification JSON key", specs, duplicate_json_key("specs/coverage.json", "schema_version", 1), 1, "Duplicate JSON property"),
        ("duplicate numeric contract JSON key", specs, duplicate_json_key("specs/contracts/capacity.json", "schema_version", 1), 1, "duplicate JSON key"),
        ("numeric units mismatch", specs, json_change("specs/contracts/resilience.json",
         lambda value: value["parameters"]["database_lock"].__setitem__("unit", "seconds")), 1, "arithmetic requires milliseconds"),
        ("fractional worker count", specs, json_change("specs/contracts/capacity.json",
         lambda value: value["parameters"]["http_workers_per_replica"].__setitem__("value", 1.5)), 1, "discrete count must be an integer"),
        ("boolean numeric parameter", specs, json_change("specs/contracts/capacity.json",
         lambda value: value["parameters"]["http_workers_per_replica"].__setitem__("value", True)), 1, "finite numeric range and value required"),
        ("missing first evidence task", specs, json_change("specs/features/F02-identity.json",
         lambda value: value["acceptance"][0].pop("first_evidence_task")), 1, "missing first evidence task"),
        ("first task does not own scenario", specs, json_change("specs/features/F02-identity.json",
         lambda value: value["acceptance"][1].__setitem__("first_evidence_task", "T02")), 1, "first evidence task does not own the scenario"),
        ("premature scenario evidence assignment", specs, json_change("specs/execution.json",
         lambda value: next(task for task in value["tasks"] if task["id"] == "T02")["required_evidence"].append("F02-AC-02")), 1, "premature evidence assignment"),
        ("parallel task lacks evidence dependency", specs, json_change("specs/execution.json",
         lambda value: next(task for task in value["tasks"] if task["id"] == "T07")["required_evidence"].append("F06-AC-01")), 1, "premature evidence assignment"),
        ("downstream evidence assignment permitted", specs, json_change("specs/execution.json",
         lambda value: next(task for task in value["tasks"] if task["id"] == "T12")["required_evidence"].append("F04-AC-01")), 0, "PASS:"),
    ]
    return spec_cases


def evidence_cases():
    evidence = [sys.executable, "scripts/check_evidence.py"]
    pilot = evidence + ["--stage", "pilot"]
    complete = evidence + ["--stage", "complete"]
    no_change = lambda root, value: None
    evidence_cases = [
        ("valid local metadata", evidence, no_change, 0, "PASS: local"),
        ("unimplemented revision", evidence, evidence_change(lambda value: value.__setitem__("revision", None)), 1, "No completed implementation revision"),
        ("unknown evidence version", evidence, evidence_change(lambda value: value.__setitem__("schema_version", 2)), 1, "constant mismatch"),
        ("duplicate evidence JSON key", evidence, duplicate_json_key("specs/implementation-evidence.json", "schema_version", 1), 1, "Duplicate JSON property"),
        ("duplicate evidence schema JSON key", evidence, duplicate_json_key("specs/evidence.schema.json", "type", "object"), 1, "Duplicate JSON property"),
        ("boolean exit code", evidence, first_gate_field("exit_code", False), 1, "wrong value type"),
        ("missing gate scope", evidence, evidence_change(lambda value: value["gates"][0].pop("scope")), 1, "missing required field"),
        ("unknown gate scope", evidence, first_gate_field("scope", "fictional"), 1, "invalid enum value"),
        ("malformed environment", evidence, first_gate_field("environment", "synthetic"), 1, "wrong value type"),
        ("empty environment", evidence, first_gate_field("environment", {}), 1, "object size outside bounds"),
        ("non-string environment", evidence, first_gate_field("environment", {"fixture": False}), 1, "wrong value type"),
        ("unknown manifest field", evidence, evidence_change(lambda value: value.__setitem__("override", True)), 1, "unknown fields"),
        ("missing runtime gate", evidence, evidence_change(lambda value: value["gates"].pop()), 1, "Runtime gates missing or unknown"),
        ("duplicate runtime gate", evidence, evidence_change(lambda value: value["gates"].append(copy.deepcopy(value["gates"][0]))), 1, "Duplicate gate IDs"),
        ("stale committed revision", evidence, evidence_change(lambda value: value.__setitem__("revision", "0" * 40)), 1, "current committed revision"),
        ("stale gate revision", evidence, first_gate_field("revision", "0" * 40), 1, "stale revision"),
        ("nonzero exit code", evidence, first_gate_field("exit_code", 1), 1, "failed, blocked or skipped gate"),
        ("skipped gate", evidence, first_gate_field("status", "skipped"), 1, "failed, blocked or skipped gate"),
        ("blocked gate", evidence, first_gate_field("status", "blocked"), 1, "failed, blocked or skipped gate"),
        ("timezone missing", evidence, first_gate_field("started_at", "2026-01-01T00:00:00"), 1, "timestamp requires timezone"),
        ("future completion", evidence, first_gate_field("finished_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()), 1, "invalid run time"),
        ("completion before start", evidence, first_gate_field("finished_at", "2000-01-01T00:00:00Z"), 1, "invalid run time"),
        ("missing artifact", evidence, evidence_change(lambda value: value["gates"][0]["artifacts"][0].__setitem__("path", "tmp/missing.txt")), 1, "Missing or empty artifact"),
        ("corrupted artifact digest", evidence, evidence_change(lambda value: value["gates"][0]["artifacts"][0].__setitem__("sha256", "0" * 64)), 1, "Artifact digest mismatch"),
        ("artifact path escape", evidence, evidence_change(lambda value: value["gates"][0]["artifacts"][0].__setitem__("path", "../outside.txt")), 1, "Evidence artifact escapes repository"),
        ("empty artifact", evidence, lambda root, value: (root / "tmp/proof.txt").write_bytes(b""), 1, "Missing or empty artifact"),
        ("oversized artifact", evidence, lambda root, value: (root / "tmp/proof.txt").write_bytes(b"x" * (10 * 1024 * 1024 + 1)), 1, "Evidence artifact exceeds 10 MiB"),
        ("missing acceptance scenario", evidence, evidence_change(lambda value: value["scenarios"].pop()), 1, "Scenario proof missing or unknown"),
        ("duplicate acceptance scenario", evidence, evidence_change(lambda value: value["scenarios"].append(copy.deepcopy(value["scenarios"][0]))), 1, "Duplicate scenario IDs"),
        ("scenario references unknown gate", evidence, evidence_change(lambda value: value["scenarios"][0].__setitem__("gate_ids", ["G-UNKNOWN"])), 1, "gate proof missing"),
        ("missing task proof", evidence, evidence_change(lambda value: value["tasks"].pop()), 1, "selected completion stage"),
        ("extra task proof", evidence, evidence_change(lambda value: value["tasks"].append({**value["tasks"][0], "id": "T99"})), 1, "selected completion stage"),
        ("failed task", evidence, evidence_change(lambda value: value["tasks"][0].__setitem__("status", "failed")), 1, "task incomplete"),
        ("task scenario omission", evidence, evidence_change(lambda value: next(task for task in value["tasks"] if task["scenario_ids"]).__setitem__("scenario_ids", [])), 1, "scenario proof incomplete"),
        ("uncommitted implementation change", evidence, lambda root, value: (root / "README.md").write_text((root / "README.md").read_text() + "\nFixture dirty change.\n"), 1, "Uncommitted implementation changes"),
        ("valid pilot metadata", pilot, stage_evidence("pilot"), 0, "PASS: pilot"),
        ("synthetic live identity", pilot, compose(stage_evidence("pilot"), evidence_change(lambda value: next(gate for gate in value["gates"] if gate["id"] == "G-IDENTITY").__setitem__("scope", "synthetic"))), 1, "synthetic identity provider cannot satisfy"),
        ("missing live approval", pilot, compose(stage_evidence("pilot"), evidence_change(lambda value: value["live_approvals"].pop())), 1, "Live approvals missing"),
        ("stale live approval", pilot, compose(stage_evidence("pilot"), evidence_change(lambda value: value["live_approvals"][0].__setitem__("revision", "0" * 40))), 1, "stale or ownerless approval"),
        ("ownerless live approval", pilot, compose(stage_evidence("pilot"), evidence_change(lambda value: value["live_approvals"][0].__setitem__("owner", ""))), 1, "string length outside bounds"),
        ("duplicate live approval", pilot, compose(stage_evidence("pilot"), evidence_change(lambda value: value["live_approvals"].append(copy.deepcopy(value["live_approvals"][0])))), 1, "Duplicate approval IDs"),
        ("valid complete metadata", complete, stage_evidence("complete"), 0, "PASS: complete"),
        ("missing cohort approval", complete, compose(stage_evidence("complete"), evidence_change(lambda value: value["live_approvals"].pop())), 1, "Live approvals missing"),
        ("unsupported evidence schema keyword", evidence, json_change("specs/evidence.schema.json",
         lambda value: value.__setitem__("unimplementedVocabulary", True)), 1, "unsupported schema keywords"),
        ("reference sibling restriction rejected", evidence, json_change("specs/evidence.schema.json",
         lambda value: value["properties"]["gates"]["items"].__setitem__("maxProperties", 0)), 1, "validation siblings of $ref are unsupported"),
        ("manifest command never executed", evidence, first_gate_field("command", "touch tmp/manifest-command-executed"), 1, "unexpected command"),
    ]
    return evidence_cases


def cases():
    return specification_cases() + evidence_cases()


def check_case(base, destination, case):
    label, command, mutate, expected, diagnostic = case
    shutil.copytree(base, destination)
    evidence = load(destination / "specs/implementation-evidence.json")
    mutation = mutate(destination, evidence)
    if mutation is not RAW_EVIDENCE:
        dump(destination / "specs/implementation-evidence.json", evidence)
    result = run(destination, command)
    output = result.stdout + result.stderr
    valid = result.returncode == expected and diagnostic in output and "Traceback" not in output
    valid &= not (destination / "tmp/manifest-command-executed").exists()
    if not valid:
        raise RuntimeError(f"{label}: expected exit {expected} and {diagnostic!r}; got exit {result.returncode}:\n{output}")


def main():
    try:
        with tempfile.TemporaryDirectory(prefix="scopegate-verifier-fixtures-") as directory:
            temporary = Path(directory)
            base = temporary / "baseline"
            revision = setup_fixture(base)
            dump(base / "specs/implementation-evidence.json", make_evidence(base, revision))
            test_cases = cases()
            for index, case in enumerate(test_cases):
                check_case(base, temporary / f"case-{index:02}", case)
            print(f"PASS: {len(test_cases)} verifier behaviors checked in isolated public fixtures.")
            print("Scope: validator metadata and rejection behavior only; no application, migration, live approval or release was executed or certified.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Validator behavior check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

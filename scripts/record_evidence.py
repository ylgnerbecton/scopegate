#!/usr/bin/env python3
"""Execute canonical release gates and bind real local proof to a committed revision."""

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from release_support import (
    MANIFEST,
    MAX_ARTIFACT,
    ReleaseFailure,
    artifact,
    clean_revision,
    ensure,
    load_json,
    public_environment,
    public_path,
    run_tool,
    safe_path,
    sanitize,
    sanitize_file,
    secret_values,
    tool_arguments,
    topological_gates,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
GATE_IDS = {
    "G-LINT", "G-DOMAIN", "G-DATABASE", "G-CONTRACT", "G-BROWSER", "G-MIGRATION",
    "G-IDENTITY", "G-BUILD", "G-RELEASE", "G-PERFORMANCE", "G-SECURITY", "G-OPERATIONS",
}
PYTEST_GATES = GATE_IDS - {"G-LINT", "G-BROWSER", "G-BUILD", "G-RELEASE"}
OUTPUTS = {
    "G-DOMAIN": ["artifacts/unit/policy-mutations.json"],
    "G-BROWSER": ["artifacts/browser/results.json", "artifacts/browser/interaction-evidence.json",
                  "artifacts/browser/tenant-delay-evidence.json"],
    "G-PERFORMANCE": ["artifacts/performance/report.json"],
    "G-OPERATIONS": ["artifacts/operations/worker-drain.json", "artifacts/operations/proxy-recovery.json",
                     "artifacts/operations/rollback-recovery.json"],
    "G-SECURITY": ["artifacts/security/backend-sbom.json", "artifacts/security/frontend-sbom.json",
                   "artifacts/security/frontend-audit.json", "artifacts/security/requirements.lock.txt"],
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def junit_results(path):
    ensure(path.is_file(), "The gate did not produce its required fresh JUnit report")
    tree = ET.parse(path)
    cases = list(tree.iter("testcase"))
    ensure(cases, "JUnit report contains no executed tests")
    ensure(not any(list(tree.iter(tag)) for tag in ("skipped", "failure", "error")),
           "JUnit contains skipped, failed or error tests")
    counters = [int(suite.get(key, "0")) for suite in tree.iter("testsuite")
                for key in ("skipped", "failures", "errors")]
    ensure(all(value == 0 for value in counters), "JUnit suite counts contain skipped, failed or error tests")
    return [
        {"file": case.get("file", ""), "classname": case.get("classname", ""),
         "name": case.get("name", ""), "result": "passed"}
        for case in cases
    ]


def browser_specs(suites):
    for suite in suites:
        yield from suite.get("specs", [])
        yield from browser_specs(suite.get("suites", []))


def browser_results(path):
    ensure(path.is_file(), "The browser gate did not produce fresh JSON results")
    report = load_json(path)
    stats = report.get("stats", {})
    ensure(not report.get("errors") and not any(stats.get(key, 0) for key in ("unexpected", "skipped", "flaky")),
           "Browser results contain errors, skipped tests, failures or flaky retries")
    passed = []
    for spec in browser_specs(report.get("suites", [])):
        ensure(spec.get("ok") is True and bool(spec.get("tests")), "Browser specification was not executed successfully")
        for test in spec["tests"]:
            attempts = test.get("results", [])
            ensure(test.get("expectedStatus") == "passed" and attempts
                   and all(attempt.get("status") == "passed" for attempt in attempts),
                   "Browser test did not pass every recorded attempt")
            passed.append({"name": "browser:" + spec["title"], "result": "passed"})
    ensure(passed, "Browser report contains no passed tests")
    return passed


def vitest_results(path):
    ensure(path.is_file(), "The domain gate did not produce fresh frontend unit results")
    report = load_json(path)
    ensure(report.get("success") is True and report.get("numTotalTests", 0) > 0,
           "Frontend unit tests did not execute successfully")
    ensure(not any(report.get(key, 0) for key in ("numFailedTests", "numPendingTests", "numTodoTests", "numFailedTestSuites", "numPendingTestSuites")),
           "Frontend unit report contains failed, skipped or todo tests")
    results = [case for suite in report.get("testResults", []) for case in suite.get("assertionResults", [])]
    ensure(results and all(case.get("status") == "passed" for case in results),
           "Frontend unit assertions were not all passed")
    return [{"name": "frontend:" + case["fullName"], "result": "passed"} for case in results]


def gate_environment(output, previous, environment, release=False):
    result = environment.copy()
    junit = output / "junit.xml"
    result["PYTEST_ADDOPTS"] = environment.get("PYTEST_ADDOPTS", "") + " " + shlex.join([
        "--junitxml=" + str(junit), "-o", "junit_family=legacy",
    ])
    result["SCOPEGATE_VITEST_RESULTS"] = str(output / "frontend-unit.json")
    result.pop("SCOPEGATE_RELEASE_GATES", None)
    if release:
        result["SCOPEGATE_RELEASE_GATES"] = json.dumps([
            {"id": gate["id"], "status": gate["status"], "exit_code": gate["exit_code"]}
            for gate in previous
        ])
    return result


def gate_process(root, command, environment, timeout):
    arguments = shlex.split(command)
    ensure(arguments and arguments[0] == "make" and all(re.fullmatch(r"[a-z][a-z-]*", arg) for arg in arguments[1:]),
           "Runtime gate entrypoints must be canonical Make targets")
    ensure(shutil.which(arguments[0]) is not None, "Missing executable: make")
    with tempfile.TemporaryFile() as raw:
        try:
            process = subprocess.Popen(
                tool_arguments(arguments), cwd=root, env=environment, stdout=raw,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            exit_code, failure = process.wait(timeout=timeout), None
        except subprocess.TimeoutExpired:
            exit_code, failure = terminate_gate(process), "Gate exceeded its execution deadline"
        raw.seek(0, os.SEEK_END)
        oversized = raw.tell() > MAX_ARTIFACT
        raw.seek(0)
        output = raw.read(MAX_ARTIFACT - 4096).decode("utf-8", errors="replace")
        if oversized:
            failure = "Gate output exceeded the size bound; the rejected log was truncated"
            output += "\n[Rejected oversized output: log truncated]\n"
    return exit_code, output, failure


def terminate_gate(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
        return process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        return process.wait(timeout=2)
    except ProcessLookupError:
        return process.wait(timeout=2)


def standalone_reports(root, gate_id, output):
    sources, reports = [], []
    for relative in OUTPUTS.get(gate_id, []):
        sources.append(safe_path(root, relative))
        name = "browser-results.json" if relative == "artifacts/browser/results.json" else sources[-1].name
        reports.append(output / name)
    ensure(len(set(reports)) == len(reports), "Duplicate standalone report destinations")
    ensure(not any(path.exists() or path.is_symlink() for path in reports),
           "Standalone report destination already exists")
    for source, destination in zip(sources, reports, strict=True):
        artifact(root, source)
        if source.suffix == ".json":
            load_json(source)
        shutil.copyfile(source, destination)
    return reports


def clear_outputs(root, gate_id):
    for relative in OUTPUTS.get(gate_id, []):
        (root / relative).unlink(missing_ok=True)


def gate_reports(root, gate_id, output):
    reports, tests = [], []
    if gate_id in PYTEST_GATES:
        reports.append(output / "junit.xml")
        tests.extend(junit_results(reports[-1]))
    if gate_id == "G-DOMAIN":
        reports.append(output / "frontend-unit.json")
        tests.extend(vitest_results(reports[-1]))
    if gate_id == "G-BROWSER":
        source = root / "artifacts/browser/results.json"
        tests.extend(browser_results(source))
    reports.extend(standalone_reports(root, gate_id, output))
    return reports, tests


def execute_gate(root, gate, revision, output, previous, environment, secrets, timeout, metadata=None):
    output.mkdir(parents=True)
    started = utc_now()
    status, exit_code, tests, reports = "failed", None, [], []
    dependencies = set(gate.get("depends_on", []))
    failed = {item["id"] for item in previous if item["status"] != "passed"}
    clear_outputs(root, gate["id"])
    try:
        ensure(not dependencies.intersection(failed), "A required predecessor gate failed")
        exit_code, log, failure = gate_process(root, gate["planned_entrypoint"],
                                              gate_environment(output, previous, environment, gate["id"] == "G-RELEASE"), timeout)
        ensure(failure is None, failure)
        ensure(exit_code == 0, f"Gate exited with code {exit_code}")
        reports, tests = gate_reports(root, gate["id"], output)
        status = "passed"
        diagnostic = None
    except (ReleaseFailure, OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        diagnostic = str(error)
        log = locals().get("log", "") + "\nEvidence collection rejected this gate: " + diagnostic + "\n"
        if dependencies.intersection(failed):
            status = "blocked"
    finished = utc_now()
    log_path = output / "command.log"
    log_path.write_text(sanitize(log or "Command completed with no output.\n", root, secrets), encoding="utf-8")
    for path in reports:
        sanitize_file(path, root, secrets)
    result_path = output / "result.json"
    write_json(result_path, {"schema_version": 1, "gate_id": gate["id"], "revision": revision,
               "command": gate["planned_entrypoint"], "status": status, "exit_code": exit_code,
               "started_at": started, "finished_at": finished, "tests": tests,
               "diagnostic": sanitize(diagnostic or "", root, secrets)})
    record = {"id": gate["id"], "scope": "synthetic", "status": status,
              "command": gate["planned_entrypoint"], "exit_code": exit_code, "revision": revision,
              "started_at": started, "finished_at": finished, "environment": metadata or public_environment(),
              "artifacts": [artifact(root, path) for path in [log_path, result_path, *reports]]}
    if status == "failed":
        tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-80:])[-12000:]
        print(f"{gate['id']} failure output (sanitized tail):\n{tail}", flush=True)
    return record, tests


def python_test_matches(name, result):
    file, separator, function = name.partition("::")
    if not separator or not file.endswith(".py"):
        return False
    actual_file = result.get("file", "").replace("\\", "/")
    if not actual_file:
        actual_file = result.get("classname", "").replace(".", "/") + ".py"
    file_matches = file == actual_file or file.endswith("/" + actual_file)
    file_matches |= actual_file.endswith("/" + file)
    actual_name = result.get("name", "")
    return file_matches and (actual_name == function or actual_name.startswith(function + "["))


def test_gate(name, gate_ids, results):
    matches = [gid for gid in gate_ids for result in results.get(gid, [])
               if result.get("result") == "passed" and (result.get("name") == name or python_test_matches(name, result))]
    ensure(matches, f"Named scenario test did not pass in its declared gates: {name}")
    return matches[0]


def scenario_proofs(root, execution, declarations, gates, results, revision, output):
    expected = {case["id"] for feature in execution["features"]
                for case in load_json(root / feature["path"])["acceptance"]}
    ensure(len({item["id"] for item in declarations}) == len(declarations)
           and {item["id"] for item in declarations} == expected,
           "Scenario declarations must match every canonical acceptance scenario exactly")
    gate_index = {gate["id"]: gate for gate in gates}
    proofs = []
    for declaration in declarations:
        proofs.append(scenario_proof(root, declaration, gate_index, results, revision, output))
    return proofs


def scenario_proof(root, declaration, gates, results, revision, output):
    gate_ids = declaration["gate_ids"]
    ensure(gate_ids and len(set(gate_ids)) == len(gate_ids) and set(gate_ids) <= set(gates),
           f"{declaration['id']}: invalid declared gates")
    names, documents, note = declaration["tests"], declaration["documents"], declaration["note"]
    ensure(names or (documents and note.startswith("Documentary:")),
           f"{declaration['id']}: documentary-only proof must be explicitly declared")
    tested = []
    for name in names:
        gid = test_gate(name, gate_ids, results)
        tested.append({"name": name, "gate_id": gid, "result": "passed",
                       "artifact": next(item for item in gates[gid]["artifacts"] if item["path"].endswith("result.json"))})
    references = []
    for relative in documents:
        public_path(relative)
        references.append(artifact(root, safe_path(root, relative)))
    proof = {"schema_version": 1, "id": declaration["id"], "revision": revision,
             "scope": "synthetic", "gate_ids": gate_ids, "tests": tested,
             "documents": references, "note": note, "documentary_only": not names}
    path = output / "scenarios" / (declaration["id"] + ".json")
    write_json(path, proof)
    return {"id": declaration["id"], "gate_ids": gate_ids, "artifact": artifact(root, path)}


def task_scenarios(task, indexed):
    if task["id"] == "T12":
        return sorted(indexed)
    return sorted({sid for sid in task["required_evidence"] if re.fullmatch(r"F\d{2}-AC-\d{2}", sid)})


def task_proofs(root, execution, scenarios, gates, revision, output):
    indexed = {scenario["id"]: scenario for scenario in scenarios}
    tasks = [task for task in execution["tasks"] if int(task["id"][1:]) <= 12]
    ensure({task["id"] for task in tasks} == {f"T{number:02d}" for number in range(13)},
           "The local release requires T00 through T12")
    records = []
    for task in tasks:
        ids = task_scenarios(task, indexed)
        ensure(set(ids) <= set(indexed), f"{task['id']}: missing scenario proof")
        path = output / "tasks" / (task["id"] + ".json")
        write_json(path, {"schema_version": 1, "id": task["id"], "revision": revision,
                   "scope": "closed local evaluation", "scenario_ids": ids,
                   "scenarios": [indexed[sid] for sid in ids], "runtime_gates": gates,
                   "required_evidence": task["required_evidence"]})
        records.append({"id": task["id"], "status": "complete", "scenario_ids": ids,
                        "artifact": artifact(root, path)})
    return records


def tool_versions(root, secrets):
    commands = {
        "git": ["git", "--version"], "make": ["make", "--version"],
        "node": ["node", "--version"], "npm": ["npm", "--version"],
        "docker": ["docker", "--version"], "uv": ["uv", "--version"],
        "ruff": [str(root / "backend/.venv/bin/ruff"), "--version"],
        "mypy": [str(root / "backend/.venv/bin/mypy"), "--version"],
        "pytest": [str(root / "backend/.venv/bin/python"), "-m", "pytest", "--version"],
        "playwright": ["node", "frontend/node_modules/@playwright/test/cli.js", "--version"],
    }
    metadata = public_environment()
    for name, command in commands.items():
        result = run_tool(root, command, timeout=15)
        ensure(result.returncode == 0 and result.stdout.strip(), f"Cannot verify required tool version: {name}")
        metadata[name] = sanitize(result.stdout.strip().splitlines()[0][:512], root, secrets)
    return metadata


def collect(root, timeout=1800):
    revision = clean_revision(root)
    execution = load_json(root / "specs/execution.json")
    gates = topological_gates(execution["runtime_gates"])
    ensure({gate["id"] for gate in gates} == GATE_IDS and gates[-1]["id"] == "G-RELEASE",
           "Release collection requires all 12 canonical gates with G-RELEASE last")
    output = root / "artifacts/evidence" / revision / uuid.uuid4().hex
    output.mkdir(parents=True)
    environment = os.environ.copy()
    secrets = secret_values(root, environment)
    manifest = {"schema_version": 1, "revision": revision, "gates": [], "scenarios": [], "tasks": [], "live_approvals": []}
    write_json(root / MANIFEST, manifest)
    metadata = tool_versions(root, secrets)
    results = {}
    for gate in gates:
        print(f"Running {gate['id']}: {gate['planned_entrypoint']}", flush=True)
        record, tests = execute_gate(root, gate, revision, output / gate["id"],
                                     manifest["gates"], environment, secrets, timeout, metadata)
        manifest["gates"].append(record)
        results[gate["id"]] = tests
        write_json(root / MANIFEST, manifest)
        print(f"{gate['id']}: {record['status']} (exit={record['exit_code']})", flush=True)
    ensure(all(gate["status"] == "passed" for gate in manifest["gates"]), "One or more runtime gates failed or were blocked")
    declarations = load_json(root / "specs/scenario-tests.json")["scenarios"]
    manifest["scenarios"] = scenario_proofs(root, execution, declarations, manifest["gates"], results, revision, output)
    manifest["tasks"] = task_proofs(root, execution, manifest["scenarios"], manifest["gates"], revision, output)
    ensure(clean_revision(root) == revision, "Implementation changed while collecting evidence")
    write_json(root / MANIFEST, manifest)
    verifier = subprocess.run(tool_arguments([sys.executable, "scripts/check_evidence.py"]), cwd=root, check=False)
    ensure(verifier.returncode == 0, "Recorded proof did not pass the strict evidence verifier")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-timeout", type=int, default=1800)
    args = parser.parse_args()
    try:
        ensure(1 <= args.gate_timeout <= 7200, "Gate deadline must be between 1 and 7200 seconds")
        manifest = collect(ROOT, args.gate_timeout)
    except (ReleaseFailure, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Release collection failed: {error}", file=sys.stderr)
        return 1
    print(f"PASS: all 12 gates, {len(manifest['scenarios'])} scenarios and 13 local tasks verified at {manifest['revision']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

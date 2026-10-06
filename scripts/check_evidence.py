#!/usr/bin/env python3
"""Fail closed when completion proof is missing, stale, unsuccessful or corrupted."""

import argparse
import hashlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evidence_shape import validate as validate_shape
from spec_io import load_json

ROOT = Path(__file__).resolve().parents[1]
LIVE = {
    "identity-provider", "notification-provider", "all-writers-fenced",
    "all-consumers-enforced", "intended-access-baseline",
    "zero-unexplained-divergence", "durable-manager-policy", "restore-reconciliation",
}


class EvidenceFailure(Exception):
    """A release proof failed verification."""


def ensure(condition, message):
    if not condition:
        raise EvidenceFailure(message)


def load(path):
    return load_json(path)


def index_unique(records, label):
    result = {record["id"]: record for record in records}
    ensure(len(result) == len(records), f"Duplicate {label} IDs")
    return result


def artifact_check(record):
    path = (ROOT / record["path"]).resolve()
    ensure(path.is_relative_to(ROOT), "Evidence artifact escapes repository")
    ensure(path.is_file() and path.stat().st_size > 0, f"Missing or empty artifact: {record['path']}")
    ensure(path.stat().st_size <= 10 * 1024 * 1024, "Evidence artifact exceeds 10 MiB")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ensure(digest == record["sha256"], f"Artifact digest mismatch: {record['path']}")


def gate_check(record, expected, revision):
    label = record["id"]
    ensure(record["status"] == "passed" and record["exit_code"] == 0, f"{label}: failed, blocked or skipped gate")
    ensure(record["revision"] == revision, f"{label}: stale revision")
    ensure(record["command"] == expected["planned_entrypoint"], f"{label}: unexpected command")
    ensure(bool(record["environment"]) and bool(record["artifacts"]), f"{label}: missing environment or artifacts")
    start = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
    finish = datetime.fromisoformat(record["finished_at"].replace("Z", "+00:00"))
    ensure(start.tzinfo is not None and finish.tzinfo is not None, f"{label}: timestamps require timezone")
    ensure(start <= finish <= datetime.now(timezone.utc), f"{label}: invalid run time")
    for artifact in record["artifacts"]:
        artifact_check(artifact)


def revision_check(evidence):
    revision = evidence["revision"]
    ensure(isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{40,64}", revision), "No completed implementation revision has been recorded")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False)
    ensure(result.returncode == 0 and result.stdout.strip() == revision, "Evidence must match the current committed revision")
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True, capture_output=True, check=False)
    ensure(dirty.returncode == 0, "Cannot inspect repository state")
    # Proof is produced after a commit. Only ignored artifact outputs and this generated manifest may change.
    changed = [line[3:] for line in dirty.stdout.splitlines()]
    ensure(all(path == "specs/implementation-evidence.json" for path in changed), "Uncommitted implementation changes invalidate revision evidence")
    return revision


def scenario_checks(evidence, features, gates):
    records = index_unique(evidence["scenarios"], "scenario")
    expected = {item["id"] for feature in features for item in feature["acceptance"]}
    ensure(set(records) == expected, f"Scenario proof missing or unknown: {sorted(expected - set(records))}")
    for record in records.values():
        ensure(bool(record["gate_ids"]) and set(record["gate_ids"]) <= set(gates), f"{record['id']}: gate proof missing")
        artifact_check(record["artifact"])
    return records


def task_checks(evidence, execution, scenarios, stage):
    records = index_unique(evidence["tasks"], "task")
    last = {"local": 12, "pilot": 13, "complete": 14}[stage]
    expected = [task for task in execution["tasks"] if int(task["id"][1:]) <= last]
    ensure(set(records) == {task['id'] for task in expected}, "Task proof must match the selected completion stage")
    for task in expected:
        ensure(task["id"] in records, f"Missing task proof: {task['id']}")
        record = records[task["id"]]
        ensure(record["status"] == "complete", f"{task['id']}: task incomplete")
        required = {sid for sid in task["required_evidence"] if re.fullmatch(r"F\d{2}-AC-\d{2}", sid)}
        ensure(required <= set(record["scenario_ids"]) <= set(scenarios), f"{task['id']}: scenario proof incomplete")
        artifact_check(record["artifact"])


def approval_checks(evidence, revision, stage):
    if stage == "local":
        return
    approvals = index_unique(evidence["live_approvals"], "approval")
    required = LIVE | ({"cohort-observation", "legacy-contraction"} if stage == "complete" else set())
    ensure(required <= set(approvals), f"Live approvals missing: {sorted(required - set(approvals))}")
    for aid in required:
        record = approvals[aid]
        ensure(record["revision"] == revision and bool(record["owner"]), f"{aid}: stale or ownerless approval")
        artifact_check(record["artifact"])


def validate(stage):
    evidence = load(ROOT / "specs/implementation-evidence.json")
    validate_shape(evidence, load(ROOT / "specs/evidence.schema.json"))
    execution = load(ROOT / "specs/execution.json")
    revision = revision_check(evidence)
    expected = index_unique(execution["runtime_gates"], "gate")
    gates = index_unique(evidence["gates"], "gate")
    ensure(set(gates) == set(expected), f"Runtime gates missing or unknown: {sorted(set(expected) - set(gates))}")
    for gid, record in gates.items():
        gate_check(record, expected[gid], revision)
    if stage != "local":
        ensure(gates["G-IDENTITY"]["scope"] == "live", "A synthetic identity provider cannot satisfy a live pilot")
    features = [load(ROOT / feature["path"]) for feature in execution["features"]]
    scenarios = scenario_checks(evidence, features, gates)
    task_checks(evidence, execution, scenarios, stage)
    approval_checks(evidence, revision, stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["local", "pilot", "complete"], default="local")
    args = parser.parse_args()
    try:
        validate(args.stage)
    except (EvidenceFailure, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Evidence check failed: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {args.stage} implementation evidence matches the committed revision and verified artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

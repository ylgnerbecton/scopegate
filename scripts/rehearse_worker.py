#!/usr/bin/env python3
"""Verify SIGTERM drain and restart of the owned local delivery container."""

import json
import time
from pathlib import Path

from release_support import ReleaseFailure, ensure, run_tool, write_json

ROOT = Path(__file__).resolve().parents[1]


def run(arguments):
    result = run_tool(ROOT, arguments, timeout=20)
    ensure(result.returncode == 0, "Owned worker lifecycle command failed")
    return result.stdout.strip()


def main():
    container = run(["docker", "compose", "ps", "-q", "worker"])
    ensure(container and "\n" not in container, "Exactly one running owned worker is required")
    started = time.monotonic()
    stopped = None
    try:
        run(["docker", "compose", "stop", "--timeout", "5", "worker"])
        state = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", container]))
        stopped = {key: state[key] for key in ["Status", "ExitCode", "OOMKilled"]}
    finally:
        run(["docker", "compose", "start", "worker"])
    elapsed = round(time.monotonic() - started, 3)
    ready = run(["docker", "inspect", "--format", "{{.State.Running}}", container]) == "true"
    passed = stopped == {"Status": "exited", "ExitCode": 0, "OOMKilled": False} and ready
    write_json(ROOT / "artifacts/operations/worker-drain.json", {
        "scope": "Actual owned local Compose worker; SIGTERM drain followed by restart",
        "stop_deadline_seconds": 5, "elapsed_seconds_including_restart": elapsed,
        "stopped": stopped, "restarted": ready, "passed": passed,
    })
    ensure(passed, "Worker did not drain with exit 0 and restart successfully")
    print(f"PASS: owned worker drained without forced termination and restarted ({elapsed}s).")


if __name__ == "__main__":
    try:
        main()
    except (ReleaseFailure, OSError, ValueError) as error:
        raise SystemExit(f"Worker lifecycle rehearsal failed: {error}") from error

#!/usr/bin/env python3
"""Validate the schema contract in an isolated, disposable PostgreSQL 18 server."""

from __future__ import annotations

import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

IMAGE = "postgres:18"
DATABASE = "scopegate_checks"
ROOT = Path(__file__).resolve().parents[1]
LABEL = "scopegate.schema-check"


class CheckFailure(Exception):
    """A prerequisite, schema, assertion, or cleanup failed."""


def run(args: list[str], *, timeout: float = 15, sql: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        input=sql,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def require(result: subprocess.CompletedProcess[str], context: str) -> str:
    if result.returncode:
        diagnostic = (result.stderr or result.stdout).strip()[-4000:]
        raise CheckFailure(f"{context} failed (exit {result.returncode}): {diagnostic}")
    return result.stdout.strip()


def psql(name: str, sql: str) -> subprocess.CompletedProcess[str]:
    return run(
        ["exec", "-i", name, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-U", "postgres", "-d", DATABASE],
        timeout=60,
        sql="SET statement_timeout = '20s'; SET lock_timeout = '3s';\n" + sql,
    )


def cleanup(name: str, owner: str) -> None:
    probe = run(["inspect", "--format", '{{ index .Config.Labels "' + LABEL + '" }}', name])
    if probe.returncode:
        if "No such object" in probe.stderr or "No such container" in probe.stderr:
            return
        require(probe, "Container ownership check")
    if probe.stdout.strip() != owner:
        raise CheckFailure("Container ownership did not match; cleanup refused.")
    require(run(["rm", "--force", name], timeout=20), "Disposable container cleanup")


def interrupted(signum: int, frame: object) -> None:
    raise InterruptedError(f"Interrupted by signal {signum}.")


def start_server(name, owner):
    require(
        run(
            [
                "run", "--detach", "--rm", "--name", name,
                "--label", LABEL + "=" + owner,
                "--network", "none", "--cpus", "0.5", "--memory", "256m",
                "--pids-limit", "128", "--stop-timeout", "5",
                "--tmpfs", "/var/lib/postgresql:rw,size=192m",
                "--env", "POSTGRES_PASSWORD=" + secrets.token_hex(24),
                "--env", "POSTGRES_DB=" + DATABASE,
                IMAGE,
            ],
            timeout=45,
        ),
        "Disposable server startup",
    )


def wait_ready(name):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready = run(["exec", name, "pg_isready", "--host", "127.0.0.1", "-U", "postgres", "-d", DATABASE], timeout=5)
        if ready.returncode == 0:
            break
        state = run(["inspect", "--format", "{{.State.Running}}", name], timeout=5)
        if state.returncode or state.stdout.strip() != "true":
            raise CheckFailure("Disposable PostgreSQL server stopped before becoming ready.")
        time.sleep(0.5)
    else:
        raise CheckFailure("Disposable PostgreSQL readiness timed out after 60 seconds.")


def run_checks(name, schema, checks):
    engine = require(psql(name, "SELECT current_setting('server_version_num');"), "Engine version check")
    if not engine.isdigit() or int(engine) // 10000 != 18:
        raise CheckFailure("The schema check requires PostgreSQL major version 18.")
    version = require(psql(name, "SELECT current_setting('server_version');"), "Engine display version")
    require(psql(name, schema), "Fresh schema DDL")
    checked = psql(name, checks)
    require(checked, "Schema assertions")
    match = re.search(r"SCHEMA_CHECKS positive=(\d+) negative=(\d+)", checked.stdout + checked.stderr)
    if not match:
        raise CheckFailure("Schema assertions did not produce their completion count.")
    positive, negative = map(int, match.groups())
    if positive < 4 or negative < 25:
        raise CheckFailure("Schema assertions did not cover the required structural cases.")
    print(f"PostgreSQL {version}: fresh DDL passed; {positive} positive and {negative} negative structural checks passed.")
    print("Scope: database constraints and scoped fixture updates. Application authorization, clocks, locking, identity verification, and migration require separate checks.")
    from transaction_probe import check
    check(name)


def prepare_inputs():
    if not shutil.which("docker"):
        raise CheckFailure("Docker is required and was not found on PATH.")
    schema = (ROOT / "specs/contracts/schema.sql").read_text(encoding="utf-8")
    checks = (ROOT / "specs/contracts/schema-checks.sql").read_text(encoding="utf-8")
    require(run(["info", "--format", "{{.ServerVersion}}"]), "Docker daemon availability")
    image = run(["image", "inspect", "--format", "{{.Id}}", IMAGE])
    if image.returncode:
        print("Fetching the PostgreSQL 18 image...", flush=True)
        require(run(["pull", IMAGE], timeout=180), "Image download")
    return schema, checks


def cleanup_result(name, owner):
    try:
        cleanup(name, owner)
        print("Disposable container cleanup confirmed.")
    except (subprocess.TimeoutExpired, CheckFailure, OSError) as error:
        print(f"Schema check cleanup failed: {error}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    owner = secrets.token_hex(12)
    name = "scopegate-schema-" + owner
    attempted = False
    result_code = 0
    signal.signal(signal.SIGTERM, interrupted)
    try:
        schema, checks = prepare_inputs()
        attempted = True
        start_server(name, owner)
        wait_ready(name)
        run_checks(name, schema, checks)
    except subprocess.TimeoutExpired as error:
        print(f"Schema check failed: Docker operation timed out after {error.timeout} seconds.", file=sys.stderr)
        result_code = 1
    except (CheckFailure, OSError, KeyboardInterrupt, InterruptedError) as error:
        print(f"Schema check failed: {error}", file=sys.stderr)
        result_code = 1
    finally:
        if attempted:
            result_code = max(result_code, cleanup_result(name, owner))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())

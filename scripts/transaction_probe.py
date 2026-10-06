"""Controlled PostgreSQL snapshot experiment; no application behavior is certified."""

import concurrent.futures
import subprocess
import time

from check_schema import CheckFailure, psql, require

KEY = 8123456789


def wait_for(name, predicate, label):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if require(psql(name, predicate), label) == "t":
            return
        time.sleep(0.05)
    raise CheckFailure(f"Transaction probe did not reach barrier: {label}")


def holder(name):
    process = subprocess.Popen(
        ["docker", "exec", "-i", name, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "scopegate_checks"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    process.stdin.write(f"BEGIN; SET application_name='scopegate_probe_holder'; SET idle_in_transaction_session_timeout='12s'; SELECT pg_advisory_xact_lock({KEY}); UPDATE probe_access SET state='revoked';\n")
    process.stdin.flush()
    try:
        wait_for(name, "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='scopegate_probe_holder' AND state='idle in transaction');", "holder ready")
    except BaseException:
        process.kill()
        process.communicate(timeout=5)
        raise
    return process


def schedule(name, combined):
    require(psql(name, "UPDATE probe_access SET state='active';"), "Reset probe")
    process = holder(name)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        statement = (
            f"SELECT pg_advisory_xact_lock_shared({KEY}), 'POLICY=' || state FROM probe_access;"
            if combined else
            f"SELECT pg_advisory_xact_lock_shared({KEY}); SELECT 'POLICY=' || state FROM probe_access;"
        )
        sql = "BEGIN; SET application_name='scopegate_probe_waiter'; SET lock_timeout='10s'; " + statement + " COMMIT;"
        future = executor.submit(psql, name, sql)
        wait_for(name, "SELECT EXISTS(SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE a.application_name='scopegate_probe_waiter' AND l.locktype='advisory' AND NOT l.granted);", "waiter blocked")
        stdout, stderr = process.communicate("COMMIT;\n", timeout=5)
        if process.returncode:
            raise CheckFailure(f"Probe holder failed: {stderr or stdout}")
        result = require(future.result(timeout=15), "Waiter decision")
        expected = "POLICY=active" if combined else "POLICY=revoked"
        if expected not in result:
            raise CheckFailure(f"Snapshot schedule result differs: expected {expected}, received {result!r}")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        executor.shutdown(wait=True, cancel_futures=True)


def check(name):
    require(psql(name, "CREATE TABLE probe_access (state TEXT NOT NULL); INSERT INTO probe_access VALUES ('active');"), "Probe fixture")
    try:
        schedule(name, combined=True)
        schedule(name, combined=False)
    finally:
        require(psql(name, "DROP TABLE probe_access;"), "Probe fixture cleanup")
    print("PASS: two controlled lock-wait schedules proved stale same-statement reads and fresh post-lock statement reads under READ COMMITTED.")

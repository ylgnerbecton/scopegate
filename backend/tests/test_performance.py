"""Measured local workload, real PostgreSQL plans and fail-closed overload.

This short synthetic sample establishes a reproducible evaluation profile. It
does not certify the proposed live traffic, full data sizes or monthly SLO.
"""

import asyncio
import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, text

from scopegate import db
from scopegate.config import get_settings
from scopegate.services import catalog, identity

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8458"


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def summarize(results, scheduled_rate=None, duration=None):
    milliseconds = [item["elapsed_ms"] for item in results]
    return {
        "requests": len(results),
        "scheduled_rate_rps": scheduled_rate,
        "schedule_seconds": duration,
        "status_counts": dict(Counter(str(item["status"]) for item in results)),
        "latency_ms": {
            "p50": percentile(milliseconds, 0.5),
            "p95": percentile(milliseconds, 0.95),
            "max": max(milliseconds, default=0),
        },
        "all_responses_within_2_seconds": all(value <= 2000 for value in milliseconds),
    }


async def request_sample(client, endpoint, opaque, scheduled_at, method="GET", body=None):
    headers = {"Cookie": f"{identity.SESSION_COOKIE}={opaque}"}
    if method == "POST":
        headers.update({"Origin": get_settings().public_origin, "X-CSRF-Token": identity.csrf_value(opaque)})
    try:
        response = await client.request(method, endpoint, headers=headers, json=body)
        status = response.status_code
    except httpx.HTTPError as error:
        status = type(error).__name__
    return {"status": status, "elapsed_ms": round((time.perf_counter() - scheduled_at) * 1000, 3)}


async def measured_phase(endpoint, sessions, rate, duration):
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
    async with httpx.AsyncClient(base_url=BASE, timeout=2, limits=limits) as client:
        started, jobs = time.perf_counter(), []
        for index in range(rate * duration):
            scheduled_at = started + index / rate
            await asyncio.sleep(max(0, scheduled_at - time.perf_counter()))
            jobs.append(
                asyncio.create_task(
                    request_sample(client, endpoint, sessions[index % len(sessions)], scheduled_at)
                )
            )
        results = await asyncio.gather(*jobs)
    return summarize(results, rate, duration)


async def simultaneous_fault(endpoint, sessions):
    async with httpx.AsyncClient(base_url=BASE, timeout=2, limits=httpx.Limits(max_connections=40)) as client:
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                request_sample(client, endpoint, sessions[index % len(sessions)], started)
                for index in range(40)
            )
        )
    return summarize(results)


async def denied_probes(endpoint, sessions, project_id, resource_id):
    async with httpx.AsyncClient(base_url=BASE, timeout=2) as client:
        results = []
        for index in range(20):
            results.append(
                await request_sample(
                    client,
                    endpoint,
                    sessions[index % len(sessions)],
                    time.perf_counter(),
                    "POST",
                    {"project_id": project_id, "resource_id": resource_id},
                )
            )
    return summarize(results)


def seed_query_profile(admin_engine, ids):
    org, project, membership = (
        ids["organizations"]["cedar"],
        ids["projects"]["harbor"],
        ids["memberships"]["viewer"],
    )
    with admin_engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO resources(id,external_key,catalog_version)
            SELECT md5('scopegate-perf-resource-'||n)::uuid,'perf-resource-'||lpad(n::text,5,'0'),1
            FROM generate_series(1,10000) n;
            INSERT INTO resource_localizations(resource_id,locale,title,description)
            SELECT md5('scopegate-perf-resource-'||n)::uuid,locale,'Performance resource '||n,
              'Synthetic query profile' FROM generate_series(1,10000) n
              CROSS JOIN (VALUES('en'),('pt'),('es'),('fr')) languages(locale)
        """)
        )
        conn.execute(
            text("""
            INSERT INTO project_resources(organization_id,project_id,resource_id)
            SELECT :org,:project,md5('scopegate-perf-resource-'||n)::uuid FROM generate_series(1,10000) n
        """),
            {"org": org, "project": project},
        )
        conn.execute(
            text("""
            INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id)
            SELECT :org,:membership,:project,md5('scopegate-perf-resource-'||n)::uuid FROM generate_series(1,10000) n
        """),
            {"org": org, "membership": membership, "project": project},
        )
        for table in (
            "resources",
            "resource_localizations",
            "project_resources",
            "resource_grants",
            "memberships",
        ):
            conn.execute(text(f"ANALYZE {table}"))
        sizes = {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in (
                "organizations",
                "projects",
                "users",
                "memberships",
                "resources",
                "resource_localizations",
                "resource_grants",
                "invitations",
                "audit_events",
                "outbox_messages",
            )
        }
    return sizes


def inspect_query_plans(viewer, ids):
    engine, counts, plans = db.get_engine(), {}, {}
    for limit in (1, 25, 100):
        observed = []

        def capture(conn, cursor, statement, parameters, context, executemany, observed=observed):
            observed.append((statement, parameters))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = catalog.list_resources(
                viewer,
                ids["organizations"]["cedar"],
                ids["projects"]["harbor"],
                "en",
                "",
                "granted",
                limit,
                None,
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(result["items"]) == limit
        counts[str(limit)] = len(observed)
        statement, parameters = next(item for item in observed if "LEFT JOIN LATERAL" in item[0])
        with engine.begin() as conn:
            plan = conn.exec_driver_sql(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement, parameters
            ).scalar_one()
        plans[str(limit)] = plan[0]
    assert len(set(counts.values())) == 1, "Resource pages must not add one SQL statement per item"
    return {"statements_per_page": counts, "constant_statement_count": True, "plans": plans}


class ConnectionSampler:
    def __init__(self, admin_engine):
        self.engine, self.peak, self.stop = admin_engine, 0, threading.Event()
        self.errors = []
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        try:
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                while not self.stop.is_set():
                    count = conn.execute(
                        text("""
                        SELECT count(*) FROM pg_stat_activity WHERE datname='scopegate_test'
                          AND application_name='scopegate' AND usename='scopegate_app'
                    """)
                    ).scalar_one()
                    self.peak = max(self.peak, count)
                    self.stop.wait(0.02)
        except Exception as error:
            self.errors.append(type(error).__name__)

    def start(self):
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive() and not self.errors


def start_server(log):
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", 8458)) != 0, "The isolated benchmark port is already occupied"
    environment = {**os.environ, "SCOPEGATE_ENVIRONMENT": "test", "SCOPEGATE_OTEL_EXPORT_ENABLED": "false"}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "scopegate.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8458",
            "--workers",
            "1",
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        cwd=ROOT / "backend",
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 10
    with httpx.Client(base_url=BASE, timeout=0.5) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("The dedicated benchmark server exited before readiness")
            try:
                if client.get("/health/ready").status_code == 200:
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    raise AssertionError("The benchmark server did not become ready within ten seconds")


@pytest.mark.performance
@pytest.mark.integration
def test_real_http_local_capacity_and_fail_closed_pressure(seed, admin_engine, ids, viewer):
    artifacts = ROOT / "artifacts/performance"
    artifacts.mkdir(parents=True, exist_ok=True)
    sizes = seed_query_profile(admin_engine, ids)
    queries = inspect_query_plans(viewer, ids)
    sessions = [
        identity.create_session(
            {
                "iss": get_settings().oidc_issuer,
                "sub": "viewer-cedar",
                "email": "jonah@example.test",
                "email_verified": True,
                "name": "Jonah",
                "auth_time": int(time.time()),
            }
        )
        for _ in range(50)
    ]
    db.get_engine().dispose()  # The sampled runtime connections now belong only to the dedicated API.
    org, project = ids["organizations"]["cedar"], ids["projects"]["harbor"]
    endpoint = f"/api/v1/organizations/{org}/projects/{project}/resources?limit=25"
    sampler, process = ConnectionSampler(admin_engine), None
    report = {
        "profile": "short-local-synthetic",
        "full_production_capacity_validated": False,
        "database": "PostgreSQL 18",
        "api_processes": 1,
        "pool_size": 4,
        "max_overflow": 1,
        "active_http_cap": 16,
        "waiting_http_cap": 8,
        "rotating_sessions": 50,
        "trace_export_enabled": False,
        "actual_table_sizes": sizes,
        "proposed_full_sizes": {
            "organizations": 100,
            "projects": 1000,
            "resources": 10000,
            "resource_localizations": 40000,
            "users": 20000,
            "memberships": 30000,
            "resource_grants": 100000,
            "invitations": 50000,
            "audit_events": 1000000,
            "outbox_messages": 5000,
        },
        "query_evidence": queries,
    }
    try:
        with (artifacts / "server.log").open("w") as log:
            process = start_server(log)
            sampler.start()
            report["workloads"] = {
                str(rate): asyncio.run(measured_phase(endpoint, sessions, rate, 2)) for rate in (10, 40, 160)
            }
            with admin_engine.begin() as conn:
                conn.execute(
                    text("SELECT id FROM sessions WHERE user_id=:user FOR UPDATE"),
                    {"user": ids["users"]["viewer-cedar"]},
                ).all()
                report["blocked_identity_fault"] = asyncio.run(simultaneous_fault(endpoint, sessions))
            report["forbidden_resource_probes"] = asyncio.run(
                denied_probes(
                    f"/api/v1/organizations/{org}/access-decisions",
                    sessions,
                    project,
                    ids["resources"]["revenue-compass"],
                )
            )
    finally:
        if sampler.thread.is_alive():
            sampler.finish()
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        report["api_connection_peak"] = sampler.peak
        report["connection_cap_observed"] = sampler.peak <= 5
        (artifacts / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    assert 1 <= sampler.peak <= 5
    assert report["forbidden_resource_probes"]["status_counts"] == {"404": 20}
    fault = report["blocked_identity_fault"]["status_counts"]
    assert set(fault) <= {"429", "503"} and sum(fault.values()) == 40, (
        "Dependency failure must never permit resource use"
    )
    steady = report["workloads"]["10"]["status_counts"]
    assert steady == {"200": 20}, "The steady synthetic workload must complete without overload"
    for phase in report["workloads"].values():
        assert set(phase["status_counts"]) <= {"200", "429", "503"}
        assert phase["all_responses_within_2_seconds"]

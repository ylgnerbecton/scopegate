"""Measured local workload, real PostgreSQL plans and fail-closed overload.

This short synthetic sample establishes a reproducible evaluation profile. It
does not certify the proposed live traffic, full data sizes or monthly SLO.
"""

import json
import threading
import time
from pathlib import Path
from runpy import run_path

import pytest
from sqlalchemy import event, text

from scopegate import db
from scopegate.config import get_settings
from scopegate.services import catalog, identity

ROOT = Path(__file__).resolve().parents[2]


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
        self.errors, self.started = [], False
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
        self.started = True
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.errors.append("sampler_stop_deadline")


def start_server(artifacts):
    current_application = run_path(str(ROOT / "scripts/rehearse_rollback.py"))["current_application"]
    return current_application(ROOT, get_settings(), port=8458, pool_size=4, max_overflow=1,
                               cpu=1, memory_bytes=512 * 1024 * 1024, logs=artifacts / "server.log")


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
    configuration = {"endpoint": endpoint, "sessions": [
        {"opaque": opaque, "csrf": identity.csrf_value(opaque)} for opaque in sessions
    ], "session_cookie": identity.SESSION_COOKIE, "origin": get_settings().public_origin}
    sampler, runtime = ConnectionSampler(admin_engine), None
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
        with start_server(artifacts) as runtime:
            report["runtime"] = runtime.metadata()
            report["runtime"]["traffic_measurement"] = (
                "Dedicated load generator container to owned API over Compose network; "
                "incoming browser, published-port and edge transport unmeasured"
            )
            assert runtime.limits == {"cpu": 1, "memory_bytes": 512 * 1024 * 1024}
            report["preflight"] = runtime.run_driver({**configuration, "operation": "warmup"})
            assert report["preflight"]["status_counts"] == {"200": 10}
            assert report["preflight"]["all_responses_within_2_seconds"]
            report["container_before_workloads"] = runtime.statistics()
            sampler.start()
            report["workloads"] = runtime.run_driver({**configuration, "operation": "load"})
            with admin_engine.begin() as conn:
                conn.execute(
                    text("SELECT id FROM sessions WHERE user_id=:user FOR UPDATE"),
                    {"user": ids["users"]["viewer-cedar"]},
                ).all()
                report["blocked_identity_fault"] = runtime.run_driver({**configuration, "operation": "fault"})
            report["forbidden_resource_probes"] = runtime.run_driver({
                **configuration, "operation": "deny", "endpoint": f"/api/v1/organizations/{org}/access-decisions",
                "body": {"project_id": project, "resource_id": ids["resources"]["revenue-compass"]},
            })
            report["load_generators"] = runtime.driver_metadata
            report["container_after_workloads"] = runtime.statistics()
    finally:
        if sampler.started:
            sampler.finish()
        report["connection_sampler"] = {"started": sampler.started, "errors": sampler.errors,
                                        "thread_stopped": not sampler.thread.is_alive()}
        report["owned_resources_removed"] = runtime is not None and runtime.cleaned
        report["api_connection_peak"] = sampler.peak
        report["connection_cap_observed"] = sampler.peak <= 5
        (artifacts / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    assert 1 <= sampler.peak <= 5
    assert sampler.started and not sampler.thread.is_alive() and not sampler.errors
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

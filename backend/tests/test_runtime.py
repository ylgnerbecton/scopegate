"""Fault proofs for transport budgets, trace privacy and uncertain outcomes."""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter, time
from types import SimpleNamespace
from typing import Annotated
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import Body, FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, TimeoutError
from starlette.requests import Request

from scopegate import config, db, journal
from scopegate.errors import AppError
from scopegate.observability import OperationalMiddleware, SafeFileSpanExporter


def isolated_settings(monkeypatch, **values):
    for name in list(os.environ):
        if name.startswith("SCOPEGATE_"):
            monkeypatch.delenv(name)
    return config.Settings(_env_file=None, outbox_key=Fernet.generate_key().decode(), **values)


@pytest.mark.security
def test_api_config_needs_no_admin_or_operations_credential(monkeypatch):
    settings = isolated_settings(
        monkeypatch, session_secret="s" * 32, cursor_secret="c" * 32,
        platform_key="p" * 32, catalog_key="k" * 32,
    )
    assert settings.component == "api" and settings.migration_database_url == ""
    assert settings.migration_ops_key == ""


@pytest.mark.security
@pytest.mark.parametrize("component", ["worker", "bootstrap", "operations"])
def test_process_config_requires_only_its_own_authority(monkeypatch, component):
    values = {"component": component}
    if component == "bootstrap":
        values["migration_database_url"] = "postgresql+psycopg://bootstrap:synthetic@localhost/local"
    if component == "operations":
        values["migration_ops_key"] = "o" * 32
    settings = isolated_settings(monkeypatch, **values)
    assert all(getattr(settings, key) == "" for key in ["session_secret", "cursor_secret", "platform_key", "catalog_key"])
    if component != "bootstrap":
        assert settings.migration_database_url == ""


@pytest.mark.security
@pytest.mark.parametrize("missing", ["session_secret", "cursor_secret", "platform_key", "catalog_key"])
def test_api_config_rejects_a_missing_required_credential(monkeypatch, missing):
    values = {"session_secret": "s" * 32, "cursor_secret": "c" * 32, "platform_key": "p" * 32, "catalog_key": "k" * 32}
    del values[missing]
    with pytest.raises(ValidationError, match=missing):
        isolated_settings(monkeypatch, **values)


@pytest.mark.security
def test_operations_and_bootstrap_reject_missing_private_authority(monkeypatch):
    with pytest.raises(ValidationError, match="migration_ops_key"):
        isolated_settings(monkeypatch, component="operations")
    with pytest.raises(ValidationError, match="separately supplied migration database URL"):
        isolated_settings(monkeypatch, component="bootstrap")


@pytest.mark.security
def test_configuration_validation_errors_do_not_print_supplied_secrets(monkeypatch):
    shared = "PRIVATE-MACHINE-CREDENTIAL" * 2
    with pytest.raises(ValidationError) as raised:
        isolated_settings(
            monkeypatch, session_secret="PRIVATE-SESSION" * 3, cursor_secret="PRIVATE-CURSOR" * 3,
            platform_key=shared, catalog_key=shared,
        )
    assert "Publisher and platform credentials must differ" in str(raised.value)
    assert "PRIVATE" not in str(raised.value)


@pytest.mark.security
@pytest.mark.operations
@pytest.mark.parametrize("code", ["55P03", "57014", "25P04", "PRIVATE-DIAGNOSTIC", None])
def test_dependency_logs_only_bounded_failure_category_and_correlation(code, caplog):
    from scopegate.main import dependency_error

    identifier = str(uuid4())
    request = Request({"type": "http", "state": {"correlation_id": identifier}})
    if code is None:
        error = TimeoutError("PRIVATE connection pool contents")
        expected = "pool_timeout"
    else:
        original = Exception("PRIVATE driver contents")
        original.sqlstate = code
        error = DBAPIError("SELECT PRIVATE SQL", {"email": "PRIVATE EMAIL"}, original)
        expected = code if not code.startswith("PRIVATE") else "database_failure"
    response = asyncio.run(dependency_error(request, error))
    entries = [json.loads(item.getMessage()) for item in caplog.records if item.name == "scopegate.dependencies"]
    assert entries == [{"event": "dependency_unavailable", "category": expected, "correlation_id": identifier}]
    assert "PRIVATE" not in caplog.text and "PRIVATE" not in response.body.decode()
    assert response.status_code == 503 and response.headers["Retry-After"] == "1"


def invoke_body(chunks, path="/commands", handler_delay=0):
    app = FastAPI()
    mutations = []

    @app.post(path)
    async def command(body: Annotated[dict, Body()]):
        mutations.append(body)
        await asyncio.sleep(handler_delay)
        return {"saved": True}

    messages = []

    async def receive():
        if not chunks:
            return {"type": "http.disconnect"}
        delay, body, more = chunks.pop(0)
        await asyncio.sleep(delay)
        return {"type": "http.request", "body": body, "more_body": more}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": b"", "headers": [(b"content-type", b"application/json")],
        "server": ("test", 80), "client": ("test", 1),
    }
    started = perf_counter()
    asyncio.run(OperationalMiddleware(app)(scope, receive, send))
    elapsed = perf_counter() - started
    start = next(item for item in messages if item["type"] == "http.response.start")
    content = b"".join(item.get("body", b"") for item in messages)
    return start, json.loads(content), mutations, elapsed


@pytest.mark.operations
def test_body_deadline_is_absolute_across_chunks_and_precedes_mutation():
    start, body, mutations, elapsed = invoke_body([
        (0.2, b'{"name":', True), (0.2, b'"late"', True), (0.2, b"}", False),
    ])
    assert start["status"] == 408 and body["error"]["code"] == "body_timeout"
    assert not mutations and 0.45 <= elapsed < 1.5
    assert dict(start["headers"])[b"x-correlation-id"]


@pytest.mark.operations
@pytest.mark.parametrize("path,limit", [("/commands", 65536), ("/api/v1/catalog/resource", 262144)])
def test_streamed_body_caps_apply_without_content_length(path, limit):
    start, body, mutations, _ = invoke_body([(0, b"x" * (limit + 1), False)], path)
    assert start["status"] == 413 and body["error"]["code"] == "payload_too_large"
    assert not mutations


@pytest.mark.operations
def test_completed_body_does_not_cancel_a_committed_handler_after_body_budget():
    start, body, mutations, elapsed = invoke_body([(0, b'{"name":"complete"}', False)], handler_delay=0.55)
    assert start["status"] == 200 and body == {"saved": True}
    assert mutations == [{"name": "complete"}] and elapsed >= 0.55


@pytest.mark.security
def test_span_export_allowlist_removes_private_attributes_and_unknown_method(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(journal_directory=tmp_path / "commands"))
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeFileSpanExporter()))
    tracer = provider.get_tracer("scopegate-runtime-test")
    with tracer.start_as_current_span("PRIVATE original span name") as span:
        span.set_attributes({
            "http.route": "/api/v1/organizations/{organization_id}/projects",
            "http.method": "PRIVATE-METHOD",
            "http.status_code": 404,
            "url.full": "https://example.test/private-account?token=PRIVATE-TOKEN",
            "http.target": "/private-account?email=private@example.test",
            "enduser.id": "private-account",
            "http.request.header.cookie": "PRIVATE-COOKIE",
        })
    provider.shutdown()
    content = (tmp_path / "traces/spans.jsonl").read_text()
    assert all(secret not in content for secret in ["PRIVATE", "private-account", "private@example.test"])
    record = json.loads(content)
    assert record["name"] == "OTHER /api/v1/organizations/{organization_id}/projects"
    assert record["attributes"] == {
        "http.route": "/api/v1/organizations/{organization_id}/projects",
        "http.method": "OTHER", "http.status_code": 404,
    }
    assert len(record["trace_id"]) == 32 and len(record["span_id"]) == 16


@pytest.mark.security
def test_actual_unmatched_path_query_cookie_and_method_do_not_enter_traces_or_logs(
    tmp_path, monkeypatch, caplog,
):
    settings = config.get_settings().model_copy(update={"journal_directory": tmp_path / "commands"})
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    from scopegate.main import app

    caplog.set_level(logging.INFO, logger="scopegate.http")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(
            "PRIVATE-METHOD", "/unmatched/private@example.test?token=PRIVATE-TOKEN",
            headers={"Cookie": "private=PRIVATE-COOKIE", "Authorization": "Bearer PRIVATE-CREDENTIAL"},
        )
    assert response.status_code == 404
    content = (tmp_path / "traces/spans.jsonl").read_text()
    http_logs = "\n".join(record.getMessage() for record in caplog.records if record.name == "scopegate.http")
    for secret in ["PRIVATE", "private@example.test", "token=", "Authorization", "Cookie"]:
        assert secret not in content and secret not in http_logs
    assert '"method": "OTHER"' in http_logs and '"route": "unmatched"' in http_logs


@pytest.mark.operations
def test_journal_outcome_io_failure_has_safe_observable_uncertainty(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(journal, "get_settings", lambda: SimpleNamespace(journal_directory=tmp_path))

    def unavailable(*args):
        raise OSError("PRIVATE secret provider failure")

    before = journal.FAILURES.labels("committed")._value.get()
    monkeypatch.setattr(journal, "append", unavailable)
    with pytest.raises(AppError) as raised:
        journal.outcome("a" * 64, "committed", {"name": "PRIVATE RESPONSE"})
    assert raised.value.status == 503 and raised.value.code == "journal_outcome_uncertain"
    assert "same command key" in raised.value.message
    assert journal.FAILURES.labels("committed")._value.get() == before + 1
    assert "journal_outcome_uncertain" in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.operations
def test_journal_handles_partial_writes_and_serializes_concurrent_records(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    write = journal.os.write
    monkeypatch.setattr(journal.os, "write", lambda descriptor, value: write(descriptor, value[:7]))
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: journal.append(path, {"index": index}), range(16)))
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert sorted(item["index"] for item in records) == list(range(16))
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.operations
def test_preparation_metadata_sync_failure_is_unavailable_before_any_command(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "get_settings", lambda: SimpleNamespace(journal_directory=tmp_path))

    def unavailable(directory):
        assert directory == tmp_path
        raise OSError("directory synchronization failed")

    monkeypatch.setattr(journal, "_sync_directory", unavailable)
    with pytest.raises(AppError) as raised:
        journal.prepare("service:test", str(uuid4()), "grant.diff", str(uuid4()), {})
    assert raised.value.status == 503 and raised.value.code == "journal_unavailable"


@pytest.mark.integration
@pytest.mark.operations
def test_post_commit_journal_failure_returns_503_and_same_key_retry_has_one_effect(client, ids, monkeypatch):
    from scopegate.services import identity

    settings = config.get_settings()
    opaque = identity.create_session({
        "iss": settings.oidc_issuer, "sub": "manager-cedar", "email": "amelia@example.test",
        "email_verified": True, "name": "Amelia Hart", "auth_time": int(time()),
    })
    client.cookies.set(identity.SESSION_COOKIE, opaque)
    key = str(uuid4())
    org, member = ids["organizations"]["cedar"], ids["memberships"]["viewer"]
    project, resource = ids["projects"]["harbor"], ids["resources"]["audience-atlas"]
    path = f"/api/v1/organizations/{org}/memberships/{member}/projects/{project}/grants"
    headers = {
        "Origin": settings.public_origin, "X-CSRF-Token": identity.csrf_value(opaque),
        "Idempotency-Key": key, "If-Match": '"v1"',
    }
    payload = {"add": [resource], "remove": [], "reason": "Reviewed bounded grant"}
    original = journal.append

    def unavailable(*args):
        raise OSError("synthetic append outage")

    monkeypatch.setattr(journal, "append", unavailable)
    response = client.patch(path, headers=headers, json=payload)
    assert response.status_code == 503 and response.json()["error"]["code"] == "journal_outcome_uncertain"
    assert response.headers["Retry-After"] == "1"
    monkeypatch.setattr(journal, "append", original)
    retried = client.patch(path, headers=headers, json=payload)
    assert retried.status_code == 200 and retried.json()["access_version"] == 2
    with db.transaction() as conn:
        assert conn.execute(text("SELECT access_version FROM memberships WHERE id=:id"), {"id": member}).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM audit_events WHERE action='grants.changed'")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM command_receipts WHERE idempotency_key=:key"), {"key": key}).scalar() == 1
        assert conn.execute(text("SELECT state FROM resource_grants WHERE membership_id=:member AND resource_id=:resource"), {"member": member, "resource": resource}).scalar() == "active"

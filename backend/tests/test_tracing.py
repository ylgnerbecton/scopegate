"""Causal diagnostics stay bounded, private and independent of access outcomes."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy import text

from scopegate import db, telemetry
from scopegate.errors import AppError
from scopegate.observability import SafeFileSpanExporter, safe_span_record
from scopegate.services import delivery, enrollment, identity


@pytest.fixture
def traces(monkeypatch):
    provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(otel_export_enabled=True))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda name, *args, **kwargs: provider.get_tracer(name))
    yield provider, exporter
    provider.shutdown()


@pytest.mark.security
def test_named_failure_preserves_parent_but_records_no_exception_payload(traces):
    provider, exporter = traces
    with provider.get_tracer("test").start_as_current_span("request") as request:
        with pytest.raises(AppError, match="PRIVATE"):
            with telemetry.span("grant.diff"):
                raise AppError(403, "permission_denied", "PRIVATE token/email/SQL")
    child = next(item for item in exporter.get_finished_spans() if item.name == "scopegate.grant.diff")
    assert child.parent.span_id == request.context.span_id
    assert child.status.status_code == StatusCode.ERROR and child.status.description is None
    assert child.events == () and child.attributes == {"scopegate.operation": "grant.diff"}
    assert "PRIVATE" not in json.dumps(safe_span_record(child))


@pytest.mark.security
def test_unknown_names_and_attributes_cannot_enter_export(traces):
    _, exporter = traces
    with telemetry.span("PRIVATE operation", "PRIVATE dependency"):
        pass
    span = exporter.get_finished_spans()[0]
    assert span.name == "scopegate.internal.other"
    assert safe_span_record(span)["attributes"] == {"scopegate.operation": "internal.other"}


def test_disabled_tracing_preserves_result_without_calling_provider(monkeypatch):
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(otel_export_enabled=False))

    def unavailable(*args, **kwargs):
        raise AssertionError("Disabled telemetry must not contact the provider")

    monkeypatch.setattr(telemetry.trace, "get_tracer", unavailable)
    with telemetry.span("grant.diff") as active:
        assert active is None
        result = "committed"
    assert result == "committed" and telemetry.capture() is None and telemetry.initialize() is None


def test_tracer_failure_does_not_replace_success_or_business_error(monkeypatch, caplog):
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(otel_export_enabled=True))

    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE provider failure")

    monkeypatch.setattr(telemetry.trace, "get_tracer", broken)
    with telemetry.span("grant.diff"):
        result = "committed"
    assert result == "committed"
    with pytest.raises(AppError, match="Business rejection"):
        with telemetry.span("grant.diff"):
            raise AppError(403, "permission_denied", "Business rejection")
    assert "telemetry_unavailable" in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.parametrize("value", [
    None, {}, "PRIVATE", "00-" + "0" * 32 + "-" + "1" * 16 + "-01",
    "00-" + "1" * 32 + "-" + "0" * 16 + "-01",
    "00-" + "1" * 32 + "-" + "2" * 16 + "-01\n",
    "ff-" + "1" * 32 + "-" + "2" * 16 + "-01",
])
def test_invalid_trace_metadata_is_discarded_without_authority(value):
    assert telemetry.valid_traceparent(value) is None
    assert not trace.get_current_span(telemetry.remote_context(value)).get_span_context().is_valid


@pytest.mark.security
def test_provider_outage_has_safe_child_and_unchanged_domain_failure(traces, monkeypatch):
    _, exporter = traces

    class UnavailableClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            raise httpx.ConnectError("PRIVATE URL, token and provider diagnostic")

    monkeypatch.setattr(identity.httpx, "Client", UnavailableClient)
    with telemetry.span("identity.login.start", "oidc"):
        with pytest.raises(AppError) as raised:
            identity._get_json(identity.get_settings().oidc_issuer + "/.well-known/openid-configuration")
    assert raised.value.status == 503 and raised.value.code == "identity_unavailable"
    parent = next(item for item in exporter.get_finished_spans() if item.name == "scopegate.identity.login.start")
    child = next(item for item in exporter.get_finished_spans() if item.name == "scopegate.identity.fetch")
    assert child.parent.span_id == parent.context.span_id and child.status.status_code == StatusCode.ERROR
    assert not child.events and "PRIVATE" not in json.dumps(safe_span_record(child))


def test_database_span_ends_after_transaction_release(traces, monkeypatch):
    _, exporter = traces
    held = {"lock": False}

    class Connection:
        def execute(self, statement):
            assert held["lock"]

    class Engine:
        @contextmanager
        def begin(self):
            held["lock"] = True
            try:
                yield Connection()
            finally:
                held["lock"] = False

    original = exporter.export
    states = []

    def export(spans):
        states.append(held["lock"])
        return original(spans)

    monkeypatch.setattr(exporter, "export", export)
    monkeypatch.setattr(db, "get_engine", lambda: Engine())
    with db.transaction():
        assert held["lock"]
    assert states == [False]


def test_batch_export_runs_outside_producer_even_when_file_io_stalls(monkeypatch, tmp_path):
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(BatchSpanProcessor(
        SafeFileSpanExporter(), max_queue_size=256, max_export_batch_size=1,
        schedule_delay_millis=500, export_timeout_millis=1000,
    ))
    entered, release = threading.Event(), threading.Event()
    producer = threading.get_ident()
    workers = []
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path.name == "traces":
            workers.append(threading.get_ident())
            entered.set()
            assert release.wait(2)
        return original(path, *args, **kwargs)

    monkeypatch.setattr("scopegate.config.get_settings", lambda: SimpleNamespace(journal_directory=tmp_path / "journal"))
    monkeypatch.setattr("pathlib.Path.mkdir", mkdir)
    try:
        with provider.get_tracer("test").start_as_current_span("request"):
            pass
        assert entered.wait(2) and workers == [workers[0]] and workers[0] != producer
    finally:
        release.set()
        provider.force_flush(timeout_millis=1000)
        provider.shutdown()


@pytest.mark.security
def test_export_failure_has_safe_diagnostics_and_failure_status(traces, monkeypatch, caplog):
    _, exporter = traces
    with telemetry.span("database.transaction", "postgresql"):
        pass

    def unavailable(*args, **kwargs):
        raise OSError("PRIVATE filesystem path and diagnostic")

    monkeypatch.setattr("scopegate.observability.os.open", unavailable)
    assert SafeFileSpanExporter().export(exporter.get_finished_spans()) == SpanExportResult.FAILURE
    assert "stage=export" in caplog.text and "PRIVATE" not in caplog.text


def invitation_body(ids):
    return {"email": "morgan@example.test", "resources": [{
        "project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"],
    }]}


@pytest.mark.integration
@pytest.mark.operations
@pytest.mark.security
def test_http_command_encrypted_outbox_and_separate_worker_failure_share_causal_trace(traces, manager, ids):
    provider, exporter = traces
    app = FastAPI()
    key = str(uuid4())

    @app.post("/trace-journey")
    def invite():
        return enrollment.create_invitation(manager, ids["organizations"]["cedar"], invitation_body(ids), key)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    with TestClient(app) as client:
        response = client.post("/trace-journey")
    assert response.status_code == 200
    with db.transaction() as conn:
        message = db.row(conn, "SELECT * FROM outbox_messages WHERE invitation_id=:id", {"id": response.json()["id"]})
    envelope = json.loads(delivery.cipher().decrypt(bytes(message["encrypted_payload"])))
    metadata = telemetry.valid_traceparent(envelope["_traceparent"])
    assert metadata and metadata.encode() not in bytes(message["encrypted_payload"])
    received = []

    def fail(message, payload):
        received.append(payload)
        assert "_traceparent" not in payload
        raise OSError("PRIVATE delivery token, email and provider URL")

    def worker():
        assert not trace.get_current_span().get_span_context().is_valid
        return delivery.process_batch("trace-worker", 1, fail)

    with ThreadPoolExecutor(max_workers=1) as executor:
        outcome = executor.submit(worker).result(timeout=5)
    assert outcome == {"claimed": 1, "delivered": 0, "failed": 1, "stale": 0}
    assert received and not list(delivery._mailbox_dir().glob("*.enc"))
    spans = exporter.get_finished_spans()
    request = next(item for item in spans if item.kind.name == "SERVER")
    command = next(item for item in spans if item.name == "scopegate.invitation.create")
    attempt = next(item for item in spans if item.name == "scopegate.delivery.attempt")
    adapter = next(item for item in spans if item.name == "scopegate.delivery.adapter")
    acknowledged = next(item for item in spans if item.name == "scopegate.delivery.acknowledge")
    assert command.parent.span_id == request.context.span_id
    assert attempt.parent.span_id == int(metadata.split("-")[2], 16)
    assert adapter.parent.span_id == acknowledged.parent.span_id == attempt.context.span_id
    assert request.context.trace_id == command.context.trace_id == attempt.context.trace_id
    assert attempt.status.status_code == adapter.status.status_code == StatusCode.ERROR
    assert not attempt.events and not adapter.events
    safe = json.dumps([safe_span_record(item) for item in spans])
    for secret in ["PRIVATE", "morgan@example.test", envelope["accept_url"], envelope["organization_id"]]:
        assert secret not in safe
    with db.transaction() as conn:
        stored = db.row(conn, "SELECT state,last_error_code FROM outbox_messages WHERE id=:id", {"id": message["id"]})
    assert stored == {"state": "pending", "last_error_code": "adapter_temporarily_unavailable"}


@pytest.mark.integration
@pytest.mark.operations
@pytest.mark.parametrize("metadata", [None, "PRIVATE invalid trace context"])
def test_legacy_or_invalid_trace_envelope_delivers_without_exposing_metadata(traces, manager, ids, admin_engine, metadata):
    enrollment.create_invitation(manager, ids["organizations"]["cedar"], invitation_body(ids), str(uuid4()))
    with admin_engine.begin() as conn:
        message = db.row(conn, "SELECT * FROM outbox_messages WHERE state='pending'", {})
        envelope = json.loads(delivery.cipher().decrypt(bytes(message["encrypted_payload"])))
        envelope.pop("_traceparent", None)
        if metadata is not None:
            envelope["_traceparent"] = metadata
        conn.execute(text("UPDATE outbox_messages SET encrypted_payload=:payload WHERE id=:id"), {
            "payload": delivery.cipher().encrypt(json.dumps(envelope).encode()), "id": message["id"],
        })
    assert delivery.process_batch("compat-trace-worker", 1)["delivered"] == 1
    path = next(delivery._mailbox_dir().glob("*.enc"))
    record = json.loads(delivery.cipher().decrypt(path.read_bytes()))
    assert "_traceparent" not in record
    assert delivery.mailbox(manager, ids["organizations"]["cedar"])["items"][0]["recipient_email"] == "morgan@example.test"


@pytest.mark.integration
@pytest.mark.operations
def test_new_trace_context_does_not_change_command_receipt_authority(traces, manager, ids):
    key = str(uuid4())
    with telemetry.span("invitation.create"):
        first = enrollment.create_invitation(manager, ids["organizations"]["cedar"], invitation_body(ids), key)
    with telemetry.span("invitation.create"):
        second = enrollment.create_invitation(manager, ids["organizations"]["cedar"], invitation_body(ids), key)
    assert first == second
    with db.transaction() as conn:
        assert conn.execute(text("SELECT count(*) FROM outbox_messages WHERE invitation_id=:id"), {"id": first["id"]}).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM command_receipts WHERE idempotency_key=:key"), {"key": key}).scalar() == 1


@pytest.mark.integration
@pytest.mark.operations
@pytest.mark.security
def test_disabled_tracing_still_commits_and_delivers_without_context(manager, ids, monkeypatch):
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(otel_export_enabled=False))
    invitation = enrollment.create_invitation(manager, ids["organizations"]["cedar"], invitation_body(ids), str(uuid4()))
    with db.transaction() as conn:
        message = db.row(conn, "SELECT * FROM outbox_messages WHERE invitation_id=:id", {"id": invitation["id"]})
    envelope = json.loads(delivery.cipher().decrypt(bytes(message["encrypted_payload"])))
    assert "_traceparent" not in envelope
    assert delivery.process_batch("disabled-trace-worker", 1)["delivered"] == 1
    assert delivery.mailbox(manager, ids["organizations"]["cedar"])["items"][0]["recipient_email"] == "morgan@example.test"

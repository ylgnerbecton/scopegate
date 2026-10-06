"""Bounded diagnostic context; telemetry never supplies command authority."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

from opentelemetry import context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from scopegate.config import get_settings

OPERATIONS = {
    "internal.other", "database.transaction", "organization.create", "project.create",
    "membership.status", "entitlement.set", "grant.diff", "report.create",
    "invitation.create", "invitation.accept", "identity.login.start", "identity.login.finish",
    "identity.metadata", "identity.keys", "identity.fetch", "identity.exchange", "delivery.attempt",
    "delivery.adapter", "delivery.claim", "delivery.acknowledge",
}
DEPENDENCIES = {"postgresql", "oidc", "outbox", "delivery"}
FAILURE_STAGES = {"initialization", "flush", "status", "start", "end", "capture", "context", "extract", "export"}
TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}\Z")
_propagator = TraceContextTextMapPropagator()
_provider: TracerProvider | None = None
_initialization_lock = threading.Lock()
logger = logging.getLogger("scopegate.telemetry")


def unavailable(stage: str) -> None:
    """Failure diagnostics contain a fixed stage, never the original error."""
    try:
        stage = stage if stage in FAILURE_STAGES else "unknown"
        logger.warning("telemetry_unavailable stage=%s", stage)
    except Exception:
        pass


def initialize() -> TracerProvider | None:
    """Own local export only when enabled and no other provider is installed."""
    global _provider
    try:
        if not get_settings().otel_export_enabled:
            return None
        with _initialization_lock:
            if _provider is not None:
                return _provider
            if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
                return None
            from scopegate.observability import SafeFileSpanExporter

            provider = TracerProvider()
            provider.add_span_processor(BatchSpanProcessor(
                SafeFileSpanExporter(), max_queue_size=256, max_export_batch_size=64,
                schedule_delay_millis=500, export_timeout_millis=1000,
            ))
            trace.set_tracer_provider(provider)
            _provider = provider
            return provider
    except Exception:
        unavailable("initialization")
        return None


def flush() -> None:
    """Best effort drain outside transactions; never a release/commit decision."""
    try:
        if _provider is not None and not _provider.force_flush(timeout_millis=1000):
            unavailable("flush")
    except Exception:
        unavailable("flush")


def mark_failed(active: Any) -> None:
    if active is not None:
        try:
            active.set_status(Status(StatusCode.ERROR))
        except Exception:
            unavailable("status")


def _start(operation: str, dependency: str | None, parent: context.Context | None):
    try:
        if not get_settings().otel_export_enabled:
            return None, None
        operation = operation if operation in OPERATIONS else "internal.other"
        attributes = {"scopegate.operation": operation}
        if dependency in DEPENDENCIES:
            attributes["scopegate.dependency"] = dependency
        active = trace.get_tracer("scopegate.boundaries").start_span(
            "scopegate." + operation, context=parent, attributes=attributes,
        )
        token = context.attach(trace.set_span_in_context(active, parent))
        return active, token
    except Exception:
        unavailable("start")
        return None, None


def _end(active: Any, token: Any) -> None:
    try:
        if token is not None:
            context.detach(token)
        if active is not None:
            active.end()
    except Exception:
        unavailable("end")


@contextmanager
def span(operation: str, dependency: str | None = None, parent: context.Context | None = None):
    active, token = _start(operation, dependency, parent)
    try:
        yield active
    except BaseException:
        mark_failed(active)
        raise
    finally:
        _end(active, token)


def traced(operation: str, dependency: str | None = None) -> Callable:
    def decorate(function: Callable) -> Callable:
        @wraps(function)
        def instrumented(*args: Any, **kwargs: Any) -> Any:
            with span(operation, dependency):
                return function(*args, **kwargs)

        return instrumented

    return decorate


def valid_traceparent(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = TRACEPARENT.fullmatch(value)
    if match is None or int(match[1], 16) == 0 or int(match[2], 16) == 0:
        return None
    return value


def capture() -> str | None:
    try:
        if not get_settings().otel_export_enabled:
            return None
        carrier: dict[str, str] = {}
        _propagator.inject(carrier)
        return valid_traceparent(carrier.get("traceparent"))
    except Exception:
        unavailable("capture")
        return None


def current_trace_id() -> str | None:
    try:
        if get_settings().otel_export_enabled:
            current = trace.get_current_span().get_span_context()
            if current.is_valid:
                return format(current.trace_id, "032x")
    except Exception:
        unavailable("context")
    return None


def remote_context(value: Any) -> context.Context:
    """Extract one bounded value; no baggage, tracestate or authority is carried."""
    try:
        value = valid_traceparent(value)
        if value is not None and get_settings().otel_export_enabled:
            return _propagator.extract({"traceparent": value}, context=context.Context())
    except Exception:
        unavailable("extract")
    return context.Context()

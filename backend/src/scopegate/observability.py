"""Low-cardinality operational signals; no emails, cookies or request payloads."""

import json
import logging
import os
import time
from uuid import UUID, uuid4

import anyio
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from prometheus_client import Counter, Gauge, Histogram
from starlette.responses import JSONResponse

REQUESTS = Counter("scopegate_http_requests_total", "Completed HTTP requests", ["route", "method", "status"])
LATENCY = Histogram(
    "scopegate_http_duration_seconds",
    "HTTP duration",
    ["route", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 2, 5),
)
ACTIVE = Gauge("scopegate_http_active", "Active requests in this worker")
REJECTED = Counter("scopegate_admission_rejections_total", "Rejected requests", ["reason"])
DRIFT = Gauge("scopegate_access_divergence", "Unresolved shadow or cutover decision mismatches")
DELIVERY_AGE = Gauge("scopegate_pending_delivery_oldest_seconds", "Age of the oldest pending delivery")
DELIVERY_FAILED = Gauge("scopegate_failed_deliveries", "Terminal delivery failures")
RESTORE_FENCES = Gauge("scopegate_restore_fences", "Organizations fenced by independent restore markers")
logger = logging.getLogger("scopegate.http")
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def bounded_method(value: str) -> str:
    return value if value in HTTP_METHODS else "OTHER"


def update_operational_metrics() -> None:
    from scopegate.services.operations import snapshot

    values = snapshot()
    DRIFT.set(values["divergent_decisions"])
    DELIVERY_AGE.set(values["pending_delivery_oldest_seconds"])
    DELIVERY_FAILED.set(values["failed_deliveries"])
    RESTORE_FENCES.set(values["restore_fences"])


class SafeFileSpanExporter(SpanExporter):
    """Local trace evidence includes no URL, query, cookie or principal attribute."""

    def export(self, spans):
        from scopegate.config import get_settings

        directory = get_settings().journal_directory.parent / "traces"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(directory / "spans.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            for span in spans:
                attributes = span.attributes or {}
                safe = {
                    key: attributes[key]
                    for key in [
                        "http.route",
                        "http.request.method",
                        "http.method",
                        "http.response.status_code",
                        "http.status_code",
                    ]
                    if key in attributes
                }
                for key in ("http.request.method", "http.method"):
                    if key in safe:
                        safe[key] = bounded_method(safe[key])
                route = safe.get("http.route", "internal")
                method = safe.get("http.request.method", safe.get("http.method", "INTERNAL"))
                record = {
                    "trace_id": format(span.context.trace_id, "032x"),
                    "span_id": format(span.context.span_id, "016x"),
                    "name": f"{method} {route}",
                    "start_ns": span.start_time,
                    "end_ns": span.end_time,
                    "status": span.status.status_code.name,
                    "attributes": safe,
                }
                os.write(descriptor, (json.dumps(record) + "\n").encode())
        finally:
            os.close(descriptor)
        return SpanExportResult.SUCCESS


def correlation(value: str | None) -> str:
    try:
        return str(UUID(value or ""))
    except ValueError:
        return str(uuid4())


class OperationalMiddleware:
    def __init__(self, app):
        self.app = app
        self.limiter = anyio.CapacityLimiter(16)
        self.waiting = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        identifier = correlation(headers.get(b"x-correlation-id", b"").decode(errors="ignore"))
        scope.setdefault("state", {})["correlation_id"] = identifier
        limit = 262144 if scope["path"].startswith("/api/v1/catalog/") else 65536
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length > limit:
            return await self.reject(scope, receive, send, identifier, 413, "payload_too_large")
        if self.waiting >= 8:
            return await self.reject(scope, receive, send, identifier, 429, "admission_exhausted")
        self.waiting += 1
        acquired = False
        try:
            with anyio.move_on_after(0.05):
                await self.limiter.acquire()
                acquired = True
        finally:
            self.waiting -= 1
        if not acquired:
            return await self.reject(scope, receive, send, identifier, 429, "admission_exhausted")
        started = time.monotonic()
        status = 500
        ACTIVE.inc()

        async def instrumented_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] += [
                    (b"x-correlation-id", identifier.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ]
            await send(message)

        try:
            body = await self.read_body(receive, limit)
            if isinstance(body, str):
                code, status = ("body_timeout", 408) if body == "timeout" else ("payload_too_large", 413)
                await self.reject(scope, receive, instrumented_send, identifier, status, code)
            else:
                delivered = False

                async def completed_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                await self.app(scope, completed_receive, instrumented_send)
        finally:
            self.limiter.release()
            ACTIVE.dec()
            route = getattr(scope.get("route"), "path", "unmatched")
            elapsed = time.monotonic() - started
            method = bounded_method(scope["method"])
            REQUESTS.labels(route, method, str(status)).inc()
            LATENCY.labels(route, method).observe(elapsed)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "route": route,
                        "method": method,
                        "status": status,
                        "duration_ms": round(elapsed * 1000, 2),
                        "correlation_id": identifier,
                    }
                )
            )

    @staticmethod
    async def read_body(receive, limit: int) -> bytes | str:
        """Read the bounded envelope before FastAPI parsing or database work."""
        body = bytearray()
        try:
            with anyio.fail_after(0.5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return "timeout"
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        return "oversize"
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        return bytes(body)
        except TimeoutError:
            return "timeout"

    @staticmethod
    async def reject(scope, receive, send, identifier: str, status: int, code: str):
        REJECTED.labels(code).inc()
        response = JSONResponse(
            {
                "error": {
                    "code": code,
                    "message": "The request cannot be admitted within its budget.",
                    "correlation_id": identifier,
                }
            },
            status_code=status,
            headers={"Retry-After": "1", "X-Correlation-ID": identifier},
        )
        await response(scope, receive, send)

"""Composition root: transport, operational guardrails and feature routers."""

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import NoOpTracerProvider
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError

from scopegate import db, telemetry
from scopegate.api import access, auth, catalog, invitations, migration, workspace
from scopegate.config import get_settings
from scopegate.dependencies import platform_actor
from scopegate.errors import AppError
from scopegate.observability import OperationalMiddleware, update_operational_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    yield
    db.get_engine().dispose()
    telemetry.flush()


app = FastAPI(title="Scopegate", version="1.0.0", lifespan=lifespan, docs_url="/docs", redoc_url=None)
app.add_middleware(OperationalMiddleware)
for router in [
    auth.router,
    workspace.router,
    catalog.router,
    access.router,
    invitations.router,
    migration.router,
]:
    app.include_router(router)


def error_response(request: Request, status: int, code: str, message: str, fields=None) -> JSONResponse:
    detail = {
        "code": code,
        "message": message,
        "correlation_id": str(getattr(request.state, "correlation_id", uuid4())),
    }
    if fields:
        detail["fields"] = fields
    headers = {"Retry-After": "1"} if status in {429, 503} else {}
    return JSONResponse({"error": detail}, status_code=status, headers=headers)


@app.exception_handler(AppError)
async def application_error(request: Request, error: AppError):
    return error_response(request, error.status, error.code, error.message)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    fields = {".".join(map(str, item["loc"])): ["Invalid value."] for item in error.errors()}
    return error_response(request, 422, "validation_error", "Review the request fields.", fields)


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, error: IntegrityError):
    return error_response(request, 409, "state_conflict", "The requested state conflicts with current data.")


@app.exception_handler(DBAPIError)
@app.exception_handler(TimeoutError)
async def dependency_error(request: Request, error):
    logging.getLogger("scopegate.dependencies").warning(
        json.dumps({
            "event": "dependency_unavailable",
            "category": dependency_failure_category(error),
            "correlation_id": str(getattr(request.state, "correlation_id", uuid4())),
        })
    )
    return error_response(
        request, 503, "database_unavailable", "The operation could not complete within its budget."
    )


def dependency_failure_category(error) -> str:
    """Driver diagnostics are reduced to a bounded code without SQL or values."""
    if isinstance(error, TimeoutError):
        return "pool_timeout"
    original = getattr(error, "orig", None)
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return code if isinstance(code, str) and re.fullmatch(r"[0-9A-Z]{5}", code) else "database_failure"


@app.exception_handler(Exception)
async def unexpected_error(request: Request, error):
    logging.getLogger("scopegate.errors").error(
        "unexpected_error", extra={"correlation_id": str(getattr(request.state, "correlation_id", uuid4()))}
    )
    return error_response(request, 500, "unexpected_error", "The operation could not be completed.")


@app.get("/health/live", operation_id="liveness")
def live():
    return {"status": "ok"}


@app.get("/health/ready", operation_id="readiness")
def ready():
    get_settings()
    with db.get_engine().connect() as conn:
        conn.execute(text("SET statement_timeout='750ms'"))
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != "0001_target":
            raise AppError(503, "schema_unavailable", "The expected schema is not ready.")
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics(principal: Annotated[dict, Depends(platform_actor)]):
    update_operational_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


telemetry.initialize()
FastAPIInstrumentor.instrument_app(
    app, excluded_urls="health/live,health/ready,metrics",
    tracer_provider=None if get_settings().otel_export_enabled else NoOpTracerProvider(),
)

generated_openapi = app.openapi


def documented_openapi():
    """Document protection enforced by the shared Request-based dependency."""
    schema = generated_openapi()
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes["sessionCookie"] = {"type": "apiKey", "in": "cookie", "name": "scopegate_session"}
    schemes["platformBearer"] = {"type": "http", "scheme": "bearer"}
    schemes["publisherBearer"] = {"type": "http", "scheme": "bearer"}
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            _document_protection(path, method, operation)
    return schema


def _document_protection(path: str, method: str, operation: dict) -> None:
    public = path.startswith("/health/") or path.startswith("/auth/")
    publisher = path.startswith("/api/v1/catalog/")
    platform = path.startswith("/api/v1/platform/") or operation["operationId"] in {
        "getEntitlementImpact",
        "setEntitlement",
    }
    machine = publisher or platform
    scheme = "publisherBearer" if publisher else "platformBearer" if platform else "sessionCookie"
    operation["security"] = [] if public else [{scheme: []}]
    if not machine:
        _document_csrf(method, operation)


def _document_csrf(method: str, operation: dict) -> None:
    if method in {"post", "patch", "put", "delete"}:
        parameters = operation.setdefault("parameters", [])
        if not any(item.get("name") == "X-CSRF-Token" for item in parameters):
            parameters.append(
                {
                    "name": "X-CSRF-Token",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "minLength": 32},
                }
            )


app.__dict__["openapi"] = documented_openapi

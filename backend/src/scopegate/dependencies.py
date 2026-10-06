"""Request identity and distinct machine authorities."""

import secrets

from fastapi import Request

from scopegate.config import get_settings
from scopegate.errors import AppError


def actor(request: Request) -> dict:
    from scopegate.services.identity import get_principal, require_csrf
    principal = get_principal(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, principal)
    principal["correlation_id"] = request.state.correlation_id
    return principal


def machine(request: Request, kind: str, expected: str) -> dict:
    supplied = request.headers.get("authorization", "")
    if not supplied.startswith("Bearer ") or not secrets.compare_digest(supplied[7:], expected):
        raise AppError(401, "machine_credential_required")
    return {"actor_key": f"service:{kind}", "kind": "service", "correlation_id": request.state.correlation_id}


def platform_actor(request: Request) -> dict:
    return machine(request, "platform", get_settings().platform_key)


def catalog_actor(request: Request) -> dict:
    return machine(request, "catalog", get_settings().catalog_key)

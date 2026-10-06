"""Browser authentication routes; provider claims never come from request headers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import RedirectResponse, Response

from scopegate.config import get_settings
from scopegate.services import identity

router = APIRouter(tags=["identity"])


@router.get("/auth/login", operation_id="startLogin")
def login(*, return_to: str = "/"):
    destination, flow = identity.start_login(return_to)
    response = RedirectResponse(destination, status_code=302)
    response.set_cookie(
        identity.FLOW_COOKIE,
        flow,
        max_age=120,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
        path="/auth",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/callback", operation_id="finishLogin")
def callback(*, request: Request, code: str, state: str):
    opaque, destination = identity.finish_login(
        code, request.cookies.get(identity.FLOW_COOKIE), state, request.cookies.get(identity.SESSION_COOKIE)
    )
    response = RedirectResponse(destination, status_code=302)
    response.delete_cookie(identity.FLOW_COOKIE, path="/auth")
    response.set_cookie(
        identity.SESSION_COOKIE,
        opaque,
        max_age=8 * 3600,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        identity.CSRF_COOKIE,
        identity.csrf_value(opaque),
        max_age=8 * 3600,
        httponly=False,
        secure=get_settings().secure_cookies,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/v1/me", operation_id="getCurrentUser")
def current_user(*, principal: Annotated[dict, Depends(identity.get_principal)]):
    return identity.me(principal)


@router.post("/api/v1/logout", operation_id="logout", status_code=204)
def logout(
    *,
    request: Request,
    principal: Annotated[dict, Depends(identity.get_principal)],
    csrf_header: Annotated[str, Header(alias="X-CSRF-Token", min_length=32)],
) -> Response:
    identity.require_csrf(request, principal)
    identity.logout(principal)
    response = Response(status_code=204)
    response.delete_cookie(identity.SESSION_COOKIE)
    response.delete_cookie(identity.CSRF_COOKIE)
    return response

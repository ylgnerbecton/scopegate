"""OIDC verification, opaque sessions and same-origin mutation protection."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import wraps
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from sqlalchemy import text

from scopegate import db, telemetry
from scopegate.config import get_settings
from scopegate.errors import AppError
from scopegate.services.common import membership_view, serialize
from scopegate.services.invariants import required_row

SESSION_COOKIE = "scopegate_session"
FLOW_COOKIE = "scopegate_oidc_flow"
CSRF_COOKIE = "scopegate_csrf"
_NETWORK_DEADLINE: ContextVar[float | None] = ContextVar("oidc_deadline", default=None)
_OIDC_SLOTS = threading.BoundedSemaphore(2)


def network_budget(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        if not _OIDC_SLOTS.acquire(blocking=False):
            raise AppError(503, "identity_busy", "Sign-in capacity is temporarily occupied. Retry shortly.")
        token = _NETWORK_DEADLINE.set(time.monotonic() + 5.0)
        try:
            return function(*args, **kwargs)
        finally:
            _NETWORK_DEADLINE.reset(token)
            _OIDC_SLOTS.release()

    operation = {"start_login": "identity.login.start", "finish_login": "identity.login.finish"}
    return telemetry.traced(operation.get(function.__name__, "internal.other"), "oidc")(bounded)


def provider_timeout():
    deadline = _NETWORK_DEADLINE.get()
    remaining = 5.0 if deadline is None else deadline - time.monotonic()
    if remaining <= 0:
        raise AppError(503, "identity_timeout", "The sign-in deadline was exceeded.")
    return httpx.Timeout(min(1.5, remaining), connect=min(0.5, remaining))


def verify_deadline():
    deadline = _NETWORK_DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise AppError(503, "identity_timeout", "The sign-in deadline was exceeded.")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _fernet() -> Fernet:
    return Fernet(get_settings().outbox_key.encode())


def _provider_url(url: str) -> str:
    settings = get_settings()
    issuer = settings.oidc_issuer.rstrip("/")
    if not url.startswith(issuer + "/"):
        raise AppError(503, "identity_unavailable", "Identity provider metadata is not allowlisted.")
    internal = getattr(settings, "oidc_internal_url", None)
    return (internal.rstrip("/") + url[len(issuer) :]) if internal else url


def _get_json(url: str) -> dict:
    try:
        with telemetry.span("identity.fetch", "oidc"):
            with httpx.Client(timeout=provider_timeout(), follow_redirects=False) as client:
                response = client.get(_provider_url(url))
                response.raise_for_status()
                verify_deadline()
                if len(response.content) > 65536:
                    raise ValueError("Oversized provider response")
                return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise AppError(
            503, "identity_unavailable", "The identity provider is temporarily unavailable."
        ) from exc


@telemetry.traced("identity.metadata", "oidc")
def provider_metadata() -> dict:
    settings = get_settings()
    issuer = settings.oidc_issuer.rstrip("/")
    metadata = _get_json(issuer + "/.well-known/openid-configuration")
    if metadata.get("issuer") != issuer:
        raise AppError(503, "identity_unavailable", "Identity provider issuer does not match configuration.")
    for name in ["authorization_endpoint", "token_endpoint", "jwks_uri"]:
        _provider_url(metadata.get(name, ""))
    if "RS256" not in metadata.get("id_token_signing_alg_values_supported", []):
        raise AppError(
            503,
            "identity_unavailable",
            "The identity provider does not support the configured signature policy.",
        )
    return metadata


@network_budget
def start_login(return_to: str = "/") -> tuple[str, str]:
    settings = get_settings()
    if (
        not return_to.startswith("/")
        or return_to.startswith("//")
        or urlparse(return_to).scheme
        or "\\" in return_to
    ):
        raise AppError(422, "validation_error", "The return destination must be a local path.")
    metadata = provider_metadata()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    flow = {
        "purpose": "oidc-flow",
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "return_to": return_to,
    }
    encrypted = _fernet().encrypt(json.dumps(flow).encode()).decode()
    params = {
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "max_age": 900,
    }
    return metadata["authorization_endpoint"] + "?" + urlencode(params), encrypted


def verify_flow(encrypted: str | None, state: str) -> dict:
    try:
        flow = json.loads(_fernet().decrypt((encrypted or "").encode(), ttl=120))
        if flow.get("purpose") != "oidc-flow" or not secrets.compare_digest(flow["state"], state):
            raise ValueError("State mismatch")
        return flow
    except (InvalidToken, ValueError, KeyError, TypeError) as exc:
        raise AppError(
            401, "authentication_failed", "The sign-in request expired or could not be verified."
        ) from exc


@telemetry.traced("identity.keys", "oidc")
def _signing_key(signed: str, metadata: dict):
    header = jwt.get_unverified_header(signed)
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise ValueError("Unsupported signing key")
    keys = _get_json(metadata["jwks_uri"])["keys"]
    key = next(
        value
        for value in keys
        if value.get("kid") == header["kid"]
        and value.get("kty") == "RSA"
        and value.get("use", "sig") == "sig"
    )
    return jwt.PyJWK.from_dict(key, algorithm="RS256").key


def _validate_audience(claims: dict) -> None:
    client_id = get_settings().oidc_client_id
    if claims.get("azp") not in {None, client_id}:
        raise ValueError("Authorized party mismatch")
    multiple = isinstance(claims["aud"], list) and len(claims["aud"]) > 1
    if multiple and claims.get("azp") != client_id:
        raise ValueError("Authorized party required")


def _validate_recent_identity(claims: dict) -> None:
    now = datetime.now(UTC).timestamp()
    auth_time = claims["auth_time"]
    valid_type = isinstance(auth_time, (int, float)) and not isinstance(auth_time, bool)
    if not valid_type or auth_time > now + 10 or now - auth_time > 900:
        raise ValueError("Recent provider authentication required")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise ValueError("Subject missing")
    email = claims.get("email", "")
    if not isinstance(email, str) or not email.strip() or len(email) > 254:
        raise ValueError("Contact email missing")


def verify_id_token(signed: str, metadata: dict, nonce: str) -> dict:
    settings = get_settings()
    try:
        public = _signing_key(signed, metadata)
        claims = jwt.decode(
            signed,
            public,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer.rstrip("/"),
            leeway=10,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce", "auth_time"]},
        )
        if not secrets.compare_digest(str(claims["nonce"]), nonce):
            raise ValueError("Nonce mismatch")
        _validate_audience(claims)
        _validate_recent_identity(claims)
        claims["email_verified"] = claims.get("email_verified") is True
        return claims
    except (jwt.PyJWTError, StopIteration, ValueError, KeyError, TypeError) as exc:
        raise AppError(401, "authentication_failed", "The identity proof could not be verified.") from exc


@network_budget
def finish_login(
    code: str, encrypted: str | None, state: str, previous_session: str | None = None
) -> tuple[str, str]:
    flow = verify_flow(encrypted, state)
    metadata = provider_metadata()
    signed = _exchange_code(metadata, flow, code)
    claims = verify_id_token(signed, metadata, flow["nonce"])
    opaque = create_session(claims, previous_session)
    return opaque, flow["return_to"]


@telemetry.traced("identity.exchange", "oidc")
def _exchange_code(metadata: dict, flow: dict, code: str) -> str:
    settings = get_settings()
    try:
        with httpx.Client(timeout=provider_timeout(), follow_redirects=False) as client:
            response = client.post(
                _provider_url(metadata["token_endpoint"]),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.oidc_client_id,
                    "redirect_uri": settings.oidc_redirect_uri,
                    "code_verifier": flow["verifier"],
                },
            )
            response.raise_for_status()
            verify_deadline()
            if len(response.content) > 65536:
                raise ValueError("Oversized token response")
            return response.json()["id_token"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise AppError(401, "authentication_failed", "The sign-in code could not be exchanged.") from exc


def create_session(claims: dict, previous_session: str | None = None) -> str:
    opaque = secrets.token_urlsafe(48)
    authenticated = datetime.fromtimestamp(claims["auth_time"], UTC)
    with db.transaction() as conn:
        if previous_session:
            conn.execute(
                text(
                    "UPDATE sessions SET revoked_at=clock_timestamp() WHERE token_hash=:hash AND revoked_at IS NULL"
                ),
                {"hash": token_hash(previous_session)},
            )
        user = required_row(
            conn,
            """
            INSERT INTO users(issuer,subject,email,display_name) VALUES(:issuer,:subject,:email,:name)
            ON CONFLICT(issuer,subject) DO UPDATE SET email=EXCLUDED.email,display_name=EXCLUDED.display_name
            RETURNING id
        """,
            {
                "issuer": claims["iss"],
                "subject": claims["sub"],
                "email": claims["email"].strip(),
                "name": claims.get("name"),
            },
        )
        conn.execute(
            text("""
            INSERT INTO sessions(token_hash,user_id,verified_email,email_verified,authenticated_at,
              claims_verified_at,created_at,last_seen_at,expires_at)
            VALUES(:hash,:user,:email,:verified,:authenticated,clock_timestamp(),statement_timestamp(),
              statement_timestamp(),statement_timestamp()+interval '30 minutes')
        """),
            {
                "hash": token_hash(opaque),
                "user": str(user["id"]),
                "email": claims["email"].strip(),
                "verified": claims["email_verified"],
                "authenticated": authenticated,
            },
        )
    return opaque


def csrf_value(opaque: str) -> str:
    secret = get_settings().session_secret.encode()
    return hmac.new(secret, ("csrf:" + opaque).encode(), hashlib.sha256).hexdigest()


def _current_session(conn, opaque: str) -> dict:
    session = db.row(
        conn, "SELECT * FROM sessions WHERE token_hash=:hash FOR UPDATE", {"hash": token_hash(opaque)}
    )
    now = db.clock(conn)
    if not session or session["revoked_at"] is not None or session["expires_at"] <= now:
        raise AppError(401, "authentication_required", "The session expired. Sign in to continue.")
    if session["created_at"] + timedelta(hours=8) <= now:
        raise AppError(401, "authentication_required", "The session expired. Sign in to continue.")
    return required_row(
        conn,
        """
        UPDATE sessions SET last_seen_at=GREATEST(last_seen_at,:now),
          expires_at=LEAST(created_at+interval '8 hours',GREATEST(expires_at,:now+interval '30 minutes'))
        WHERE id=:id RETURNING *
    """,
        {"id": str(session["id"]), "now": now},
    )


def get_principal(request: Request) -> dict:
    opaque = request.cookies.get(SESSION_COOKIE, "")
    if len(opaque) < 43 or len(opaque) > 256:
        raise AppError(401, "authentication_required", "Sign in to continue.")
    with db.transaction() as conn:
        session = _current_session(conn, opaque)
        user = required_row(
            conn,
            "SELECT email,display_name,issuer,subject FROM users WHERE id=:id",
            {"id": str(session["user_id"])},
        )
    return {
        "user_id": str(session["user_id"]),
        "session_id": str(session["id"]),
        "actor_key": f"user:{session['user_id']}",
        "verified_email": session["verified_email"],
        "email_verified": session["email_verified"],
        "authenticated_at": session["authenticated_at"],
        "claims_verified_at": session["claims_verified_at"],
        "email": user["email"],
        "display_name": user["display_name"],
        "correlation_id": str(getattr(request.state, "correlation_id", uuid4())),
        "csrf_token": csrf_value(opaque),
    }


def require_csrf(request: Request, principal: dict) -> None:
    origin = request.headers.get("origin", "")
    if origin != get_settings().public_origin.rstrip("/"):
        raise AppError(403, "csrf_failed", "The request origin could not be verified.")
    submitted = request.headers.get("x-csrf-token", "")
    if not submitted or not hmac.compare_digest(submitted, principal["csrf_token"]):
        raise AppError(403, "csrf_failed", "The request could not be verified. Refresh and retry.")


def logout(principal: dict) -> None:
    with db.transaction() as conn:
        conn.execute(
            text("UPDATE sessions SET revoked_at=clock_timestamp() WHERE id=:id AND revoked_at IS NULL"),
            {"id": principal["session_id"]},
        )


def me(principal: dict) -> dict:
    with db.transaction() as conn:
        memberships = db.rows(
            conn,
            """
            SELECT m.*,u.email,u.display_name,o.name AS organization_name
            FROM memberships m JOIN organizations o ON o.id=m.organization_id JOIN users u ON u.id=m.user_id
            WHERE m.user_id=:user ORDER BY o.name,m.id LIMIT 101
        """,
            {"user": principal["user_id"]},
        )
    return serialize(
        {
            "id": principal["user_id"],
            "email": principal["email"],
            "display_name": principal["display_name"],
            "email_verified": principal["email_verified"],
            "csrf_token": principal["csrf_token"],
            "memberships": [
                {**membership_view(item), "organization_name": item["organization_name"]}
                for item in memberships[:100]
            ],
        }
    )

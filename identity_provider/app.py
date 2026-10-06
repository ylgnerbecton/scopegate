"""Independent local OIDC fixture. Refuses deployment outside a local environment."""

from __future__ import annotations

import base64
import hashlib
import html
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode

import anyio
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

ENVIRONMENT = os.getenv("SCOPEGATE_ENVIRONMENT", "local")
if ENVIRONMENT not in {"local", "test"}:
    raise RuntimeError(
        "The local identity fixture is restricted to local and test environments"
    )
ISSUER = os.getenv("SCOPEGATE_OIDC_ISSUER", "http://localhost:8901").rstrip("/")
CLIENT_ID = os.getenv("SCOPEGATE_OIDC_CLIENT_ID", "scopegate-local")
REDIRECT_URI = os.getenv(
    "SCOPEGATE_OIDC_REDIRECT_URI", "http://localhost:5187/auth/callback"
)
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_ID = secrets.token_hex(12)
CODES: dict[str, dict] = {}
CODE_LOCK = threading.Lock()
ACCOUNTS = {
    "manager": {
        "sub": "manager-cedar",
        "email": "amelia@example.test",
        "name": "Amelia Brooks",
        "email_verified": True,
    },
    "viewer": {
        "sub": "viewer-cedar",
        "email": "jonah@example.test",
        "name": "Jonah Reed",
        "email_verified": True,
    },
    "reviewer": {
        "sub": "staff-operator",
        "email": "rowan@example.test",
        "name": "Rowan Vale",
        "email_verified": True,
    },
    "recipient": {
        "sub": "guest-invite",
        "email": "morgan@example.test",
        "name": "Morgan Lane",
        "email_verified": True,
    },
    "birch": {
        "sub": "manager-birch",
        "email": "ellis@example.test",
        "name": "Ellis Park",
        "email_verified": True,
    },
    "unverified": {
        "sub": "demo-unverified",
        "email": "morgan@example.test",
        "name": "Unverified account",
        "email_verified": False,
    },
}
app = FastAPI(title="Scopegate local identity fixture", docs_url=None, redoc_url=None)


def b64url(number: int) -> str:
    return (
        base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big"))
        .rstrip(b"=")
        .decode()
    )


@app.get("/.well-known/openid-configuration")
def discovery():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["openid", "email", "profile"],
    }


@app.get("/jwks")
def jwks():
    numbers = PRIVATE_KEY.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KEY_ID,
                "n": b64url(numbers.n),
                "e": b64url(numbers.e),
            }
        ]
    }


def validate_authorize(params: dict[str, str]) -> None:
    if (
        params.get("client_id") != CLIENT_ID
        or params.get("redirect_uri") != REDIRECT_URI
    ):
        raise HTTPException(400, "Unknown client or callback")
    if (
        params.get("response_type") != "code"
        or "openid" not in params.get("scope", "").split()
    ):
        raise HTTPException(400, "Authorization code with openid scope is required")
    if (
        params.get("code_challenge_method") != "S256"
        or len(params.get("code_challenge", "")) != 43
    ):
        raise HTTPException(400, "A valid S256 challenge is required")
    if not params.get("state") or not params.get("nonce"):
        raise HTTPException(400, "State and nonce are required")


@app.get("/authorize", response_class=HTMLResponse)
def authorize(request: Request):
    params = dict(request.query_params)
    validate_authorize(params)
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k, quote=True)}" value="{html.escape(v, quote=True)}">'
        for k, v in params.items()
    )
    choices = "".join(
        f'<button type="submit" name="account" value="{key}"><strong>{html.escape(str(account["name"]))}</strong><span>{html.escape(str(account["email"]))}</span></button>'
        for key, account in ACCOUNTS.items()
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Scopegate • Sign in</title><style>body{{margin:0;background:#f5f7fb;font:16px system-ui;color:#1e293b;display:grid;place-items:center;min-height:100vh}}main{{background:white;border:1px solid #dce2ec;border-radius:20px;padding:36px;width:min(440px,80vw);box-shadow:0 20px 60px #263f5b12}}h1{{font-size:26px;margin:8px 0}}p{{color:#64748b;line-height:1.6}}.brand{{color:#4f46e5;font-weight:750}}button{{display:block;width:100%;text-align:left;background:#fff;border:1px solid #dce2ec;border-radius:10px;margin:12px 0;padding:14px 18px;cursor:pointer}}button:hover,button:focus-visible{{border-color:#4f46e5;background:#f5f3ff}}span{{display:block;color:#64748b;margin-top:4px;font-size:13px}}.note{{font-size:12px;border-top:1px solid #e2e8f0;padding-top:20px}}</style><main><div class="brand">Scopegate</div><h1>Choose a local account</h1><p>This independent identity provider establishes your session. Access is verified separately by the workspace.</p><form method="post">{hidden}{choices}</form><p class="note">Synthetic accounts for the local demonstration. No messages are sent to external addresses.</p></main></html>"""


@app.post("/authorize")
async def select_account(request: Request):
    params = await bounded_form(request)
    validate_authorize(params)
    account = ACCOUNTS.get(params.get("account", ""))
    if not account:
        raise HTTPException(400, "Choose an account")
    code = secrets.token_urlsafe(32)
    with CODE_LOCK:
        now = int(time.time())
        for existing in list(CODES):
            if CODES[existing]["expires_at"] <= now:
                del CODES[existing]
        if len(CODES) >= 1000:
            raise HTTPException(429, "Too many outstanding authorization requests")
        CODES[code] = {
            **account,
            "nonce": params["nonce"],
            "challenge": params["code_challenge"],
            "redirect_uri": params["redirect_uri"],
            "auth_time": now,
            "expires_at": now + 120,
        }
    return RedirectResponse(
        f"{REDIRECT_URI}?{urlencode({'code': code, 'state': params['state']})}",
        status_code=303,
    )


async def bounded_form(request: Request) -> dict[str, str]:
    body = bytearray()
    try:
        with anyio.fail_after(0.5):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 8192:
                    raise HTTPException(413, "Request too large")
                body.extend(chunk)
        decoded = body.decode("utf-8")
    except TimeoutError as error:
        raise HTTPException(408, "Request body deadline exceeded") from error
    except UnicodeDecodeError as error:
        raise HTTPException(400, "Invalid form encoding") from error
    return {key: values[0] for key, values in parse_qs(decoded).items()}


def valid_grant(params: dict[str, str], grant: dict | None) -> bool:
    if grant is None or grant["expires_at"] <= time.time():
        return False
    verifier = params.get("code_verifier", "")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return (
        params.get("grant_type") == "authorization_code"
        and params.get("client_id") == CLIENT_ID
        and params.get("redirect_uri") == REDIRECT_URI
        and 43 <= len(verifier) <= 128
        and secrets.compare_digest(challenge, grant["challenge"])
    )


@app.post("/token")
async def token(request: Request):
    params = await bounded_form(request)
    with CODE_LOCK:
        grant = CODES.pop(params.get("code", ""), None)
    if not valid_grant(params, grant):
        return JSONResponse(
            {"error": "invalid_grant"},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )
    assert grant is not None
    now = int(time.time())
    claims = {
        key: grant[key]
        for key in ["sub", "email", "name", "email_verified", "nonce", "auth_time"]
    }
    claims.update(iss=ISSUER, aud=CLIENT_ID, iat=now, exp=now + 300)
    signed = jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": KEY_ID})
    return JSONResponse(
        {
            "id_token": signed,
            "access_token": secrets.token_urlsafe(32),
            "token_type": "Bearer",
            "expires_in": 300,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "environment": ENVIRONMENT}

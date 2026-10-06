"""Identity trust boundaries and an independent code/PKCE/signature exchange."""

import base64
import hashlib
import importlib.util
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.requests import Request

from scopegate.config import Settings, get_settings
from scopegate.errors import AppError
from scopegate.services import identity


def rsa_jwk(key):
    numbers = key.public_key().public_numbers()

    def encode(number):
        return (
            base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big"))
            .rstrip(b"=")
            .decode()
        )

    return {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": encode(numbers.n),
        "e": encode(numbers.e),
    }


@pytest.fixture
def signed_identity(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(identity, "_get_json", lambda url: {"keys": [rsa_jwk(key)]})
    now = int(time.time())
    settings = get_settings()
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_client_id,
        "sub": "immutable-subject",
        "email": "morgan@example.test",
        "email_verified": True,
        "nonce": "expected-nonce",
        "iat": now,
        "exp": now + 300,
        "auth_time": now,
    }

    def signed(**changes):
        return jwt.encode({**claims, **changes}, key, algorithm="RS256", headers={"kid": "test-key"})

    return signed


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://other.example.test"},
        {"aud": "another-client"},
        {"nonce": "wrong"},
        {"exp": 1},
        {"auth_time": 1},
        {"azp": "another-client"},
        {"auth_time": None},
    ],
)
def test_identity_rejects_wrong_proof(signed_identity, changes):
    with pytest.raises(AppError) as error:
        identity.verify_id_token(
            signed_identity(**changes), {"jwks_uri": get_settings().oidc_issuer + "/jwks"}, "expected-nonce"
        )
    assert error.value.status_code == 401


def test_verified_claim_is_boolean(signed_identity):
    result = identity.verify_id_token(
        signed_identity(email_verified="true"),
        {"jwks_uri": get_settings().oidc_issuer + "/jwks"},
        "expected-nonce",
    )
    assert result["email_verified"] is False


@pytest.mark.security
def test_unsigned_and_unknown_key_are_rejected(signed_identity):
    token = jwt.encode({"sub": "x"}, key="", algorithm="none")
    with pytest.raises(AppError):
        identity.verify_id_token(token, {"jwks_uri": get_settings().oidc_issuer + "/jwks"}, "nonce")
    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode({"sub": "x"}, foreign, algorithm="RS256", headers={"kid": "unknown"})
    with pytest.raises(AppError):
        identity.verify_id_token(token, {"jwks_uri": get_settings().oidc_issuer + "/jwks"}, "nonce")


@pytest.mark.security
def test_production_rejects_fixture_configuration():
    with pytest.raises(ValueError):
        Settings(environment="production")


@pytest.mark.security
def test_csrf_binds_session_and_origin():
    opaque = secrets.token_urlsafe(48)
    csrf = identity.csrf_value(opaque)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"origin", get_settings().public_origin.encode()), (b"x-csrf-token", csrf.encode())],
        }
    )
    identity.require_csrf(request, {"csrf_token": csrf})
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"origin", b"https://other.example.test"), (b"x-csrf-token", csrf.encode())],
        }
    )
    with pytest.raises(AppError):
        identity.require_csrf(request, {"csrf_token": csrf})
    assert identity.csrf_value(secrets.token_urlsafe(48)) != csrf


@pytest.mark.identity
def test_independent_provider_enforces_pkce_and_single_use():
    path = Path(__file__).resolve().parents[2] / "identity_provider/app.py"
    spec = importlib.util.spec_from_file_location("scopegate_test_provider", path)
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    client = TestClient(provider.app)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": provider.CLIENT_ID,
        "redirect_uri": provider.REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
        "state": "state-test",
        "nonce": "nonce-test",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "account": "recipient",
    }
    selected = client.post("/authorize", data=params, follow_redirects=False)
    assert selected.status_code == 303
    code = parse_qs(urlparse(selected.headers["location"]).query)["code"][0]
    exchange = {
        "grant_type": "authorization_code",
        "client_id": provider.CLIENT_ID,
        "redirect_uri": provider.REDIRECT_URI,
        "code": code,
        "code_verifier": verifier,
    }
    result = client.post("/token", data=exchange)
    assert result.status_code == 200
    claims = jwt.decode(
        result.json()["id_token"],
        provider.PRIVATE_KEY.public_key(),
        algorithms=["RS256"],
        audience=provider.CLIENT_ID,
        issuer=provider.ISSUER,
    )
    assert claims["nonce"] == "nonce-test" and claims["sub"] == "guest-invite"
    assert client.post("/token", data=exchange).status_code == 400
    selected = client.post("/authorize", data=params, follow_redirects=False)
    exchange["code"] = parse_qs(urlparse(selected.headers["location"]).query)["code"][0]
    exchange["code_verifier"] = secrets.token_urlsafe(48)
    assert client.post("/token", data=exchange).status_code == 400
    params["redirect_uri"] = "https://other.example.test/callback"
    assert client.post("/authorize", data=params).status_code == 400


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["expiry", "revocation"])
def test_session_wait_rechecks_clock_and_cannot_revive(seed, admin_engine, settings, monkeypatch, failure):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Event

    from sqlalchemy import text

    from scopegate import db

    opaque = identity.create_session(
        {
            "iss": settings.oidc_issuer,
            "sub": "viewer-cedar",
            "email": "jonah@example.test",
            "name": "Jonah Reed",
            "email_verified": True,
            "auth_time": time.time(),
        }
    )
    with admin_engine.connect() as reader:
        expires = reader.execute(
            text("SELECT expires_at FROM sessions WHERE token_hash=:hash"),
            {"hash": identity.token_hash(opaque)},
        ).scalar_one()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"cookie", f"scopegate_session={opaque}".encode())],
        }
    )
    clock_called = Event()
    original_clock = db.clock

    def fresh_clock(conn):
        clock_called.set()
        return expires + timedelta(seconds=1) if failure == "expiry" else original_clock(conn)

    monkeypatch.setattr(db, "clock", fresh_clock)
    with admin_engine.connect() as blocker, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = blocker.begin()
        blocker.execute(
            text("SELECT id FROM sessions WHERE token_hash=:hash FOR UPDATE"),
            {"hash": identity.token_hash(opaque)},
        )
        future = executor.submit(identity.get_principal, request)
        deadline = time.monotonic() + 0.2
        waiting = False
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            while time.monotonic() < deadline:
                waiting = bool(
                    observer.execute(
                        text(
                            "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND application_name='scopegate' AND wait_event_type='Lock' AND query LIKE '%FROM sessions%FOR UPDATE%' LIMIT 1"
                        )
                    ).scalar()
                )
                if waiting:
                    break
                Event().wait(0.002)
        assert waiting and not clock_called.is_set(), (
            "The policy clock must be read only after the controlled row wait"
        )
        if failure == "revocation":
            blocker.execute(
                text("UPDATE sessions SET revoked_at=clock_timestamp() WHERE token_hash=:hash"),
                {"hash": identity.token_hash(opaque)},
            )
        transaction.commit()
        with pytest.raises(AppError) as error:
            future.result(timeout=2)
        assert error.value.status == 401 and clock_called.is_set()
    with admin_engine.connect() as reader:
        current_expiry = reader.execute(
            text("SELECT expires_at FROM sessions WHERE token_hash=:hash"),
            {"hash": identity.token_hash(opaque)},
        ).scalar_one()
    assert current_expiry == expires


@pytest.mark.integration
def test_reauthentication_rotates_opaque_session_and_does_not_merge_email(seed, settings, ids):
    from scopegate import db

    user_ids = {"manager": ids["users"]["manager-cedar"], "viewer": ids["users"]["viewer-cedar"]}
    with db.transaction() as conn:
        original_memberships = db.rows(
            conn, "SELECT * FROM memberships WHERE user_id IN (:manager,:viewer) ORDER BY id", user_ids
        )
    claims = {
        "iss": settings.oidc_issuer,
        "sub": "viewer-cedar",
        "email": "amelia@example.test",
        "name": "Jonah Reed",
        "email_verified": True,
        "auth_time": time.time(),
    }
    manager_opaque = identity.create_session({**claims, "sub": "manager-cedar", "name": "Amelia Brooks"})
    first = identity.create_session(claims)
    second = identity.create_session(claims, first)
    assert first != second
    with db.transaction() as conn:
        first_row = db.row(
            conn, "SELECT * FROM sessions WHERE token_hash=:hash", {"hash": identity.token_hash(first)}
        )
        second_row = db.row(
            conn, "SELECT * FROM sessions WHERE token_hash=:hash", {"hash": identity.token_hash(second)}
        )
        manager_row = db.row(
            conn, "SELECT * FROM sessions WHERE token_hash=:hash", {"hash": identity.token_hash(manager_opaque)}
        )
        users = db.rows(conn, "SELECT id,issuer,subject,email FROM users WHERE id IN (:manager,:viewer)", user_ids)
        current_memberships = db.rows(
            conn, "SELECT * FROM memberships WHERE user_id IN (:manager,:viewer) ORDER BY id", user_ids
        )
    assert first_row["revoked_at"] is not None and second_row["revoked_at"] is None
    assert str(second_row["user_id"]) == user_ids["viewer"]
    assert str(manager_row["user_id"]) == user_ids["manager"]
    assert manager_row["user_id"] != second_row["user_id"]
    assert manager_row["email_verified"] is True and second_row["email_verified"] is True
    assert manager_row["verified_email"] == second_row["verified_email"] == "amelia@example.test"
    assert {(user["issuer"], user["subject"]) for user in users} == {
        (settings.oidc_issuer, "manager-cedar"), (settings.oidc_issuer, "viewer-cedar")
    }
    assert {str(user["id"]) for user in users} == set(user_ids.values())
    assert {user["email"] for user in users} == {"amelia@example.test"}
    assert current_memberships == original_memberships

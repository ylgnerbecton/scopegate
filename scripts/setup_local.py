#!/usr/bin/env python3
"""Create local-only secrets once without exposing them in output."""

import base64
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]


def upgrade_runtime_password(path):
    values = dict(line.split("=", 1) for line in path.read_text().splitlines()
                  if "=" in line and not line.startswith("#"))
    if values.get("SCOPEGATE_APP_DB_PASSWORD"):
        return
    parsed = urlsplit(values["SCOPEGATE_DATABASE_URL"])
    if parsed.username != "scopegate_app" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Existing configuration needs an explicit independent runtime database credential")
    password = secrets.token_urlsafe(32)
    values["SCOPEGATE_APP_DB_PASSWORD"] = password
    values["SCOPEGATE_DATABASE_URL"] = urlunsplit(parsed._replace(
        netloc=f"scopegate_app:{password}@{parsed.hostname}:{parsed.port}"))
    temporary = path.with_suffix(".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    temporary.replace(path)
    print("Separated local runtime database credential; run bootstrap before restarting services.")


def main():
    path = ROOT / ".env"
    if path.exists():
        upgrade_runtime_password(path)
        print("Local environment already exists; preserved.")
        return
    password = secrets.token_urlsafe(32)
    application_password = secrets.token_urlsafe(32)
    data = {
        "SCOPEGATE_ENVIRONMENT": "local", "SCOPEGATE_DB_PASSWORD": password,
        "SCOPEGATE_APP_DB_PASSWORD": application_password,
        "SCOPEGATE_DATABASE_URL": f"postgresql+psycopg://scopegate_app:{application_password}@localhost:5547/scopegate",
        "SCOPEGATE_MIGRATION_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@localhost:5547/scopegate",
        "SCOPEGATE_PUBLIC_ORIGIN": "http://localhost:5187", "SCOPEGATE_OIDC_ISSUER": "http://localhost:8901",
        "SCOPEGATE_OIDC_INTERNAL_URL": "http://localhost:8901", "SCOPEGATE_OIDC_REDIRECT_URI": "http://localhost:5187/auth/callback",
        "SCOPEGATE_OUTBOX_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        **{f"SCOPEGATE_{name}": secrets.token_urlsafe(36) for name in ("SESSION_SECRET", "CURSOR_SECRET", "PLATFORM_KEY", "CATALOG_KEY", "MIGRATION_OPS_KEY")},
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("\n".join(f"{key}={value}" for key, value in data.items()) + "\n")
    print("Created protected local environment. Secrets are generated, never printed.")


if __name__ == "__main__":
    main()

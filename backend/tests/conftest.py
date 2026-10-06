"""Real PostgreSQL fixtures isolated from the running synthetic workspace."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scopegate.config import Settings, get_settings
from scopegate.db import get_engine
from scopegate.seed import MEMBERSHIPS, ORGS, PROJECTS, RESOURCES, USERS
from scopegate.seed import seed as seed_database

ROOT = Path(__file__).resolve().parents[2]
local = Settings()
runtime_url = make_url(local.database_url).set(database="scopegate_test")
admin_url = make_url(local.migration_database_url).set(database="scopegate_test")
os.environ["SCOPEGATE_ENVIRONMENT"] = "test"
os.environ["SCOPEGATE_DATABASE_URL"] = runtime_url.render_as_string(hide_password=False)
os.environ["SCOPEGATE_MIGRATION_DATABASE_URL"] = admin_url.render_as_string(hide_password=False)
os.environ["SCOPEGATE_JOURNAL_DIRECTORY"] = str(ROOT / "artifacts/test-journal")
os.environ["SCOPEGATE_MAILBOX_DIRECTORY"] = str(ROOT / "artifacts/test-mailbox")
get_settings.cache_clear()


@pytest.fixture(scope="session")
def admin_engine():
    if runtime_url.database != "scopegate_test" or admin_url.host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Tests must use the isolated local scopegate_test database.")
    control = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with control.connect() as connection:
        if not connection.execute(text("SELECT 1 FROM pg_database WHERE datname='scopegate_test'")).scalar():
            connection.exec_driver_sql("CREATE DATABASE scopegate_test")
    control.dispose()
    config = Config(str(ROOT / "backend/alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(admin_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO scopegate_app")
        connection.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.exec_driver_sql(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO scopegate_app"
        )
        connection.exec_driver_sql("REVOKE UPDATE,DELETE,TRUNCATE ON audit_events FROM scopegate_app")
        connection.exec_driver_sql("REVOKE ALL ON alembic_version FROM scopegate_app")
        connection.exec_driver_sql("GRANT SELECT ON alembic_version TO scopegate_app")
        connection.exec_driver_sql("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO scopegate_app")
    yield engine
    get_engine().dispose()
    engine.dispose()


@pytest.fixture
def seed(admin_engine):
    with admin_engine.begin() as connection:
        names = (
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename<>'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        connection.exec_driver_sql(
            "TRUNCATE " + ",".join('"' + name + '"' for name in names) + " RESTART IDENTITY CASCADE"
        )
        value = seed_database(connection)
    for directory in [get_settings().journal_directory, get_settings().mailbox_directory]:
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.rglob("*"):
            if path.is_file():
                path.unlink()
    return value


@pytest.fixture
def engine(seed):
    return get_engine()


@pytest.fixture
def conn(engine):
    with engine.begin() as connection:
        yield connection


@pytest.fixture
def actors(seed):
    names = {
        "manager": "manager-cedar",
        "viewer": "viewer-cedar",
        "reviewer": "staff-operator",
        "recipient": "guest-invite",
        "birch": "manager-birch",
    }
    emails = {
        "manager": "amelia@example.test",
        "viewer": "jonah@example.test",
        "reviewer": "rowan@example.test",
        "recipient": "morgan@example.test",
        "birch": "ellis@example.test",
    }
    values = {}
    for key, subject in names.items():
        values[key] = {
            "user_id": USERS[subject],
            "actor_key": f"user:{USERS[subject]}",
            "email": emails[key],
            "verified_email": emails[key],
            "email_verified": True,
            "authenticated_at": datetime.now(UTC),
            "claims_verified_at": datetime.now(UTC),
            "correlation_id": str(uuid4()),
            "csrf_token": "test-proof",
        }
    values["platform"] = {"actor_key": "service:platform", "kind": "service", "correlation_id": str(uuid4())}
    values["catalog"] = {"actor_key": "service:catalog", "kind": "service", "correlation_id": str(uuid4())}
    return values


@pytest.fixture
def manager(actors):
    return actors["manager"]


@pytest.fixture
def viewer(actors):
    return actors["viewer"]


@pytest.fixture
def reviewer(actors):
    return actors["reviewer"]


@pytest.fixture
def recipient(actors):
    return actors["recipient"]


@pytest.fixture
def client(seed):
    from scopegate.main import app

    with TestClient(app, raise_server_exceptions=False, base_url="http://localhost:5187") as value:
        yield value


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def ids():
    return {
        "users": USERS,
        "organizations": ORGS,
        "projects": PROJECTS,
        "resources": RESOURCES,
        "memberships": MEMBERSHIPS,
    }

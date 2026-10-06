"""Primary database access and the shared ordered transaction protocol."""

from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from scopegate.config import get_settings
from scopegate.errors import AppError


@lru_cache
def get_engine() -> Engine:
    config = get_settings()
    return create_engine(
        config.database_url, isolation_level="READ COMMITTED", pool_size=config.pool_size,
        max_overflow=config.max_overflow, pool_timeout=0.1, pool_pre_ping=True,
        connect_args={"connect_timeout": 1, "application_name": "scopegate"},
    )


@contextmanager
def transaction():
    with get_engine().begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout='250ms'"))
        connection.execute(text("SET LOCAL statement_timeout='750ms'"))
        connection.execute(text("SET LOCAL transaction_timeout='1200ms'"))
        yield connection


def rows(connection: Connection, sql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(item) for item in connection.execute(text(sql), parameters or {}).mappings()]


def row(connection: Connection, sql: str, parameters: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = connection.execute(text(sql), parameters or {}).mappings().first()
    return dict(result) if result is not None else None


def clock(connection: Connection) -> datetime:
    return connection.execute(text("SELECT clock_timestamp()")).scalar_one()


def lock_resources(connection: Connection, resource_ids, exclusive: bool = False) -> list[dict[str, Any]]:
    locked = []
    mode = "UPDATE" if exclusive else "SHARE"
    for identifier in sorted(set(str(item) for item in resource_ids)):
        resource = row(connection, f"SELECT * FROM resources WHERE id=:id FOR {mode}", {"id": identifier})
        if resource is None:
            raise AppError(404, "resource_not_found")
        locked.append(resource)
    return locked


def lock_org(connection: Connection, organization_id, exclusive: bool = True) -> dict[str, Any]:
    organization = row(connection, "SELECT * FROM organizations WHERE id=:id", {"id": str(organization_id)})
    if organization is None:
        raise AppError(404, "organization_not_found")
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    connection.execute(text(f"SELECT {function}(:key)"), {"key": organization["lock_key"]})
    current = row(connection, "SELECT * FROM organizations WHERE id=:id", {"id": str(organization_id)})
    assert current is not None
    return current


all = rows
one = row

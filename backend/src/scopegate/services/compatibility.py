"""A bounded synthetic rehearsal for containment, never a private-data adapter.

The caller supplies one transaction over explicit temporary rehearsal tables.
These helpers are deliberately absent from the HTTP application surface.
"""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services.common import literal_search_pattern


def organization_metadata(conn: Any, organization_id: str) -> dict:
    record = db.row(
        conn,
        "SELECT id,name,resource_keys,locale FROM compat_organizations WHERE id=:id",
        {"id": organization_id},
    )
    if record is None:
        raise AppError(404, "organization_not_found", "Organization was not found.")
    keys = [key.strip() for key in (record["resource_keys"] or "").split(",") if key.strip()]
    return {
        "id": str(record["id"]),
        "name": record["name"] or "Untitled organization",
        "resource_keys": keys,
        "locale": record["locale"] or "en",
    }


def approve_user(conn: Any, organization_id: str, organization_name: str, email: str) -> dict:
    normalized = email.strip().lower()
    denied = db.row(
        conn, "SELECT email FROM compat_denied_addresses WHERE email=:email", {"email": normalized}
    )
    if denied:
        raise AppError(403, "approval_denied", "This address requires an explicit reviewed decision.")
    # Identity creation cannot overwrite existing organization metadata.
    conn.execute(
        text("""
        INSERT INTO compat_organizations(id,name) VALUES(:id,:name) ON CONFLICT(id) DO NOTHING
    """),
        {"id": organization_id, "name": organization_name},
    )
    user_id = str(uuid4())
    conn.execute(
        text("INSERT INTO compat_users(id,email,organization_id) VALUES(:id,:email,:org)"),
        {"id": user_id, "email": normalized, "org": organization_id},
    )
    return {"id": user_id, "organization_id": organization_id, "email": normalized}


def search_resources(conn: Any, organization_id: str, query: str, limit: int = 25) -> list[dict]:
    if not 1 <= limit <= 100:
        raise AppError(422, "validation_error", "Limit must be between 1 and 100.")
    return db.rows(
        conn,
        """
        SELECT external_key,title FROM compat_resources WHERE organization_id=:org
          AND (external_key ILIKE :query ESCAPE '\\' OR title ILIKE :query ESCAPE '\\')
        ORDER BY external_key LIMIT :limit
    """,
        {"org": organization_id, "query": literal_search_pattern(query), "limit": limit},
    )


def replace_assignments(
    conn: Any,
    organization_id: str,
    user_id: str,
    resource_keys: list[str],
    after_delete: Callable[[], None] | None = None,
) -> None:
    user = db.row(
        conn,
        "SELECT id FROM compat_users WHERE id=:user AND organization_id=:org",
        {"user": user_id, "org": organization_id},
    )
    if user is None:
        raise AppError(404, "membership_not_found", "The scoped membership was not found.")
    if len(resource_keys) > 100 or len(resource_keys) != len(set(resource_keys)):
        raise AppError(422, "validation_error", "The assignment list must be bounded and unique.")
    conn.execute(
        text("DELETE FROM compat_assignments WHERE organization_id=:org AND user_id=:user"),
        {"org": organization_id, "user": user_id},
    )
    if after_delete:
        after_delete()
    if resource_keys:
        conn.execute(
            text("""
            INSERT INTO compat_assignments(organization_id,user_id,external_key)
            SELECT :org,:user,unnest(CAST(:keys AS text[]))
        """),
            {"org": organization_id, "user": user_id, "keys": resource_keys},
        )

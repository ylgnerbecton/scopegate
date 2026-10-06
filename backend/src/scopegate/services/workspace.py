"""Bounded workspace metadata and audited account provisioning."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services.common import (
    actor_value,
    audit,
    check_version,
    cursor_uuid,
    decode_cursor,
    enforce_writable,
    journaled,
    literal_search_pattern,
    membership_view,
    page,
    receipt,
    require_member,
    save_receipt,
    select_fields,
)

ORG_FIELDS = ("id", "name", "status")
PROJECT_FIELDS = ("id", "organization_id", "name", "status")


def list_organizations(actor: Any, limit: int, cursor: str | None) -> dict:
    scope = ["organizations", actor_value(actor, "user_id")]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        items = db.rows(
            conn,
            """
            SELECT o.id,o.name,o.status FROM organizations o JOIN memberships m ON m.organization_id=o.id
            WHERE m.user_id=:user AND m.status='active' AND o.status='active'
              AND (m.expires_at IS NULL OR m.expires_at>clock_timestamp())
              AND (CAST(:marker AS uuid) IS NULL OR o.id>CAST(:marker AS uuid))
            ORDER BY o.id LIMIT :limit
        """,
            {"user": str(actor_value(actor, "user_id")), "marker": marker, "limit": limit + 1},
        )
    return page(items, limit, scope)


def get_organization(actor: Any, organization_id: str) -> dict:
    with db.transaction() as conn:
        require_member(conn, actor, organization_id)
        organization = db.row(
            conn, "SELECT id,name,status FROM organizations WHERE id=:org", {"org": organization_id}
        )
    assert organization is not None
    return select_fields(organization, ORG_FIELDS)


@journaled("organization.create", lambda actor, body, key: (str(body["id"]), key, body))
def create_organization(actor: Any, body: dict, key: str) -> dict:
    organization_id = str(body["id"])
    with db.transaction() as conn:
        user = db.row(
            conn, "SELECT id FROM users WHERE id=:user", {"user": str(body["initial_manager_user_id"])}
        )
        if not user:
            raise AppError(422, "verified_user_required", "An existing verified identity is required.")
        created = db.row(
            conn,
            """
            INSERT INTO organizations(id,name) VALUES(:org,:name) ON CONFLICT(id) DO NOTHING
            RETURNING id,name,status
        """,
            {"org": organization_id, "name": body["name"]},
        )
        db.lock_org(conn, organization_id, exclusive=True)
        stored = receipt(conn, actor, organization_id, "organization.create", key, body)
        if stored is not None:
            return stored
        if not created:
            raise AppError(409, "organization_exists", "The supplied organization ID already exists.")
        conn.execute(
            text("""
            INSERT INTO memberships(organization_id,user_id,role,kind)
            VALUES(:org,:user,'access_manager','customer')
        """),
            {"org": organization_id, "user": str(body["initial_manager_user_id"])},
        )
        response = select_fields(created, ORG_FIELDS)
        audit(
            conn,
            actor,
            organization_id,
            "organization.created",
            "organization",
            organization_id,
            {"initial_manager_user_id": str(body["initial_manager_user_id"])},
        )
        save_receipt(conn, actor, organization_id, "organization.create", key, body, response, 201)
        return response


def list_projects(actor: Any, organization_id: str, limit: int, cursor: str | None) -> dict:
    scope = ["projects", organization_id, actor_value(actor, "user_id")]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        require_member(conn, actor, organization_id)
        items = db.rows(
            conn,
            """
            SELECT id,organization_id,name,status FROM projects WHERE organization_id=:org
              AND (CAST(:marker AS uuid) IS NULL OR id>CAST(:marker AS uuid)) ORDER BY id LIMIT :limit
        """,
            {"org": organization_id, "marker": marker, "limit": limit + 1},
        )
    return page(items, limit, scope)


@journaled("project.create", lambda actor, organization_id, body, key: (organization_id, key, body))
def create_project(actor: Any, organization_id: str, body: dict, key: str) -> dict:
    with db.transaction() as conn:
        db.lock_org(conn, organization_id, exclusive=True)
        require_member(conn, actor, organization_id, manager=True)
        stored = receipt(conn, actor, organization_id, "project.create", key, body)
        if stored is not None:
            return stored
        enforce_writable(conn, organization_id)
        project_id = str(uuid4())
        created = db.row(
            conn,
            """
            INSERT INTO projects(id,organization_id,name) VALUES(:id,:org,:name)
            RETURNING id,organization_id,name,status
        """,
            {"id": project_id, "org": organization_id, "name": body["name"]},
        )
        assert created is not None
        response = select_fields(created, PROJECT_FIELDS)
        audit(conn, actor, organization_id, "project.created", "project", project_id, {"name": body["name"]})
        save_receipt(conn, actor, organization_id, "project.create", key, body, response, 201)
        return response


def list_memberships(
    actor: Any, organization_id: str, limit: int, cursor: str | None, query: str = ""
) -> dict:
    scope = ["memberships", organization_id, actor_value(actor, "user_id"), query]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        items = db.rows(
            conn,
            """
            SELECT m.*,u.display_name,u.email FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.organization_id=:org AND (CAST(:marker AS uuid) IS NULL OR m.id>CAST(:marker AS uuid))
              AND (u.email ILIKE :query ESCAPE '\\' OR COALESCE(u.display_name,'') ILIKE :query ESCAPE '\\')
            ORDER BY m.id LIMIT :limit
        """,
            {
                "org": organization_id,
                "marker": marker,
                "limit": limit + 1,
                "query": literal_search_pattern(query),
            },
        )
    return page([membership_view(item) for item in items], limit, scope)


def _target_membership(conn: Any, organization_id: str, membership_id: str) -> dict:
    membership = db.row(
        conn,
        """
        SELECT m.*,u.display_name,u.email FROM memberships m JOIN users u ON u.id=m.user_id
        WHERE m.organization_id=:org AND m.id=:member FOR UPDATE OF m
    """,
        {"org": organization_id, "member": membership_id},
    )
    if not membership:
        raise AppError(404, "membership_not_found", "Membership was not found.")
    return membership


def _protect_continuity(conn: Any, organization_id: str, membership: dict, desired: str) -> None:
    durable = membership["role"] == "access_manager" and membership["kind"] == "customer"
    if not durable or desired != "suspended" or membership["status"] != "active":
        return
    remaining = db.row(
        conn,
        """
        SELECT count(*) AS count FROM memberships WHERE organization_id=:org AND id<>:member
          AND role='access_manager' AND kind='customer' AND status='active' AND expires_at IS NULL
    """,
        {"org": organization_id, "member": str(membership["id"])},
    )
    assert remaining is not None
    if remaining["count"] == 0:
        raise AppError(409, "last_manager_required", "At least one active customer manager must remain.")


@journaled(
    "membership.status",
    lambda actor, organization_id, membership_id, body, key, version: (
        organization_id,
        key,
        {"membership_id": membership_id, "expected_version": version, **body},
    ),
)
def change_membership(
    actor: Any, organization_id: str, membership_id: str, body: dict, key: str, version: int
) -> dict:
    payload = {"membership_id": membership_id, "expected_version": version, **body}
    with db.transaction() as conn:
        db.lock_org(conn, organization_id, exclusive=True)
        require_member(conn, actor, organization_id, manager=True)
        stored = receipt(conn, actor, organization_id, "membership.status", key, payload)
        if stored is not None:
            return stored
        enforce_writable(conn, organization_id)
        membership = _target_membership(conn, organization_id, membership_id)
        check_version(membership["access_version"], version)
        _protect_continuity(conn, organization_id, membership, body["status"])
        if membership["status"] != body["status"]:
            updated = db.row(
                conn,
                """
                UPDATE memberships SET status=:status,access_version=access_version+1
                WHERE organization_id=:org AND id=:member RETURNING *
            """,
                {"org": organization_id, "member": membership_id, "status": body["status"]},
            )
            assert updated is not None
            membership.update(updated)
            audit(
                conn,
                actor,
                organization_id,
                "membership.status_changed",
                "membership",
                membership_id,
                {"status": body["status"], "access_version": membership["access_version"]},
            )
        response = membership_view(membership)
        save_receipt(conn, actor, organization_id, "membership.status", key, payload, response)
        return response


def list_audit(
    actor: Any,
    organization_id: str,
    limit: int,
    cursor: str | None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
) -> dict:
    _validate_time_range(from_time, to_time)
    scope = [
        "audit-newest-v1",
        organization_id,
        actor_value(actor, "user_id"),
        action,
        target_type,
        target_id,
        from_time,
        to_time,
    ]
    marker_time, marker_id = _audit_marker(cursor, scope)
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        items = db.rows(
            conn,
            """
            SELECT a.id,a.action,a.target_type,a.target_id,a.actor_key,a.safe_change_summary,a.created_at,
              a.correlation_id,u.display_name AS actor_display_name
            FROM audit_events a LEFT JOIN users u ON u.id=a.actor_user_id WHERE a.organization_id=:org
              AND (CAST(:marker_time AS timestamptz) IS NULL
                OR (a.created_at,a.id)<(CAST(:marker_time AS timestamptz),CAST(:marker_id AS uuid)))
              AND (CAST(:action AS text) IS NULL OR a.action=:action)
              AND (CAST(:target_type AS text) IS NULL OR a.target_type=:target_type)
              AND (CAST(:target_id AS text) IS NULL OR a.target_id=:target_id)
              AND (CAST(:from_time AS timestamptz) IS NULL OR a.created_at>=:from_time)
              AND (CAST(:to_time AS timestamptz) IS NULL OR a.created_at<=:to_time)
            ORDER BY a.created_at DESC,a.id DESC LIMIT :limit
        """,
            {
                "org": organization_id,
                "marker_time": marker_time,
                "marker_id": marker_id,
                "limit": limit + 1,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "from_time": from_time,
                "to_time": to_time,
            },
        )
    return page(items, limit, scope, sort_key=("created_at", "id"))


def _audit_marker(cursor: str | None, scope: Any) -> tuple[datetime | None, str | None]:
    marker = decode_cursor(cursor, scope)
    if marker is None:
        return None, None
    try:
        if not isinstance(marker, list) or len(marker) != 2:
            raise ValueError("invalid marker shape")
        timestamp = datetime.fromisoformat(marker[0])
        identifier = str(UUID(marker[1]))
        if timestamp.utcoffset() is None:
            raise ValueError("timezone required")
    except (ValueError, TypeError, AttributeError) as error:
        raise AppError(422, "validation_error", "The audit cursor marker is invalid.") from error
    return timestamp, identifier


def _validate_time_range(from_time: datetime | None, to_time: datetime | None) -> None:
    for value in (from_time, to_time):
        if value is not None and value.utcoffset() is None:
            raise AppError(422, "validation_error", "Audit timestamps require a timezone offset.")
    if from_time and to_time and from_time > to_time:
        raise AppError(422, "validation_error", "The audit start time must precede its end time.")

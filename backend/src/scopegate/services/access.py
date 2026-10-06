"""Scoped grant diffs and one policy for resource reads and protected writes."""

from typing import Any
from uuid import uuid4

from sqlalchemy import text

from scopegate import db
from scopegate.domain.policy import AccessContext, evaluate
from scopegate.errors import AppError
from scopegate.services.common import (
    actor_value,
    audit,
    check_version,
    cursor_uuid,
    enforce_writable,
    journaled,
    page,
    receipt,
    require_member,
    require_project,
    save_receipt,
    serialize,
)
from scopegate.services.workspace import _target_membership


def _policy_rows(
    conn: Any, actor: Any, organization_id: str, project_id: str, resource_ids: list[str]
) -> list[dict]:
    return db.rows(
        conn,
        """
        SELECT r.id AS resource_id,r.status AS resource_status,p.status AS project_status,
          pr.status AS entitlement_status,m.status AS membership_status,m.expires_at,
          o.status AS organization_status,m.role,g.state AS grant_state
        FROM resources r JOIN project_resources pr ON pr.resource_id=r.id
        JOIN projects p ON p.organization_id=pr.organization_id AND p.id=pr.project_id
        JOIN organizations o ON o.id=p.organization_id
        JOIN memberships m ON m.organization_id=o.id AND m.user_id=:user
        LEFT JOIN resource_grants g ON g.organization_id=m.organization_id AND g.membership_id=m.id
          AND g.project_id=p.id AND g.resource_id=r.id
        WHERE pr.organization_id=:org AND pr.project_id=:project
          AND r.id=ANY(CAST(:ids AS uuid[]))
    """,
        {
            "org": organization_id,
            "project": project_id,
            "user": str(actor_value(actor, "user_id")),
            "ids": [str(value) for value in resource_ids],
        },
    )


def _decision(row: dict, now: Any) -> dict:
    context = AccessContext(
        organization_active=row["organization_status"] == "active",
        membership_active=row["membership_status"] == "active",
        membership_expires_at=row["expires_at"],
        project_active=row["project_status"] == "active",
        entitlement_active=row["entitlement_status"] == "active",
        resource_published=row["resource_status"] == "published",
        grant_active=row["grant_state"] == "active",
        now=now,
    )
    decision = evaluate(context)
    return {"allowed": decision.allowed, "reason": decision.reason}


def authorize_resources(
    conn: Any, actor: Any, organization_id: str, project_id: str, resource_ids: list[str]
) -> None:
    rows = _policy_rows(conn, actor, organization_id, project_id, resource_ids)
    if len(rows) != len(resource_ids):
        raise AppError(404, "resource_not_found", "One or more resources were not found.")
    now = db.clock(conn)
    for item in rows:
        if item["grant_state"] != "active":
            raise AppError(404, "resource_not_found", "One or more resources were not found.")
        decision = _decision(item, now)
        if not decision["allowed"]:
            raise AppError(403, decision["reason"], "Current access does not allow using these resources.")


def own_decision(actor: Any, organization_id: str, body: dict) -> dict:
    project_id, resource_id = str(body["project_id"]), str(body["resource_id"])
    with db.transaction() as conn:
        require_member(conn, actor, organization_id)
        rows = _policy_rows(conn, actor, organization_id, project_id, [resource_id])
        if not rows or (rows[0]["role"] != "access_manager" and rows[0]["grant_state"] != "active"):
            raise AppError(404, "resource_not_found", "Resource was not found.")
        return _decision(rows[0], db.clock(conn))


def get_grants(
    actor: Any, organization_id: str, membership_id: str, project_id: str, limit: int, cursor: str | None
) -> dict:
    scope = ["grants", organization_id, membership_id, project_id, actor_value(actor, "user_id")]
    with db.transaction() as conn:
        db.lock_org(conn, organization_id, exclusive=False)
        require_member(conn, actor, organization_id, manager=True)
        require_project(conn, organization_id, project_id)
        member = db.row(
            conn,
            "SELECT access_version FROM memberships WHERE organization_id=:org AND id=:member",
            {"org": organization_id, "member": membership_id},
        )
        if not member:
            raise AppError(404, "membership_not_found", "Membership was not found.")
        marker = cursor_uuid(cursor, scope, member["access_version"])
        items = db.rows(
            conn,
            """
            SELECT resource_id,state FROM resource_grants WHERE organization_id=:org
              AND membership_id=:member AND project_id=:project
              AND (CAST(:marker AS uuid) IS NULL OR resource_id>CAST(:marker AS uuid))
            ORDER BY resource_id LIMIT :limit
        """,
            {
                "org": organization_id,
                "member": membership_id,
                "project": project_id,
                "marker": marker,
                "limit": limit + 1,
            },
        )
        result = page(items, limit, scope, sort_key="resource_id", version=member["access_version"])
    return {
        "membership_id": membership_id,
        "project_id": project_id,
        "access_version": member["access_version"],
        **result,
    }


def _validate_additions(
    conn: Any, organization_id: str, project_id: str, member: dict, project: dict, additions: list[str]
) -> None:
    if not additions:
        return
    expired = member["expires_at"] is not None and member["expires_at"] <= db.clock(conn)
    if member["status"] != "active" or expired or project["status"] != "active":
        raise AppError(409, "membership_inactive", "Additions require an active membership and project.")
    allowed = db.rows(
        conn,
        """
        SELECT pr.resource_id FROM project_resources pr JOIN resources r ON r.id=pr.resource_id
        WHERE pr.organization_id=:org AND pr.project_id=:project AND pr.status='active'
          AND r.status='published' AND pr.resource_id=ANY(CAST(:ids AS uuid[]))
    """,
        {"org": organization_id, "project": project_id, "ids": additions},
    )
    if len(allowed) != len(additions):
        raise AppError(
            409, "grant_not_entitled", "Every added resource must be published and entitled in this project."
        )


def _require_entitlement_pairs(
    conn: Any, organization_id: str, project_id: str, resources: list[str]
) -> None:
    if not resources:
        return
    owned = db.rows(
        conn,
        """
        SELECT resource_id FROM project_resources WHERE organization_id=:org AND project_id=:project
          AND resource_id=ANY(CAST(:ids AS uuid[]))
    """,
        {"org": organization_id, "project": project_id, "ids": resources},
    )
    if len(owned) != len(resources):
        raise AppError(404, "resource_not_found", "One or more resources were not found.")


def _preflight_grants(actor: Any, organization_id: str, project_id: str, resources: list[str]) -> None:
    """Conceal global existence before taking locks; this grants no authority."""
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        require_project(conn, organization_id, project_id)
        _require_entitlement_pairs(conn, organization_id, project_id, resources)


def _preflight_use(actor: Any, organization_id: str, project_id: str, resources: list[str]) -> None:
    with db.transaction() as conn:
        require_member(conn, actor, organization_id)
        require_project(conn, organization_id, project_id)
        authorize_resources(conn, actor, organization_id, project_id, resources)


def _change_grants(
    conn: Any,
    organization_id: str,
    membership_id: str,
    project_id: str,
    additions: list[str],
    removals: list[str],
) -> list[dict]:
    params = {"org": organization_id, "member": membership_id, "project": project_id}
    added = (
        db.rows(
            conn,
            """
        INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id,state)
        SELECT :org,:member,:project,unnest(CAST(:ids AS uuid[])),'active'
        ON CONFLICT(organization_id,membership_id,project_id,resource_id) DO UPDATE
        SET state='active',updated_at=clock_timestamp() WHERE resource_grants.state<>'active'
        RETURNING resource_id,state
    """,
            {**params, "ids": additions},
        )
        if additions
        else []
    )
    removed = (
        db.rows(
            conn,
            """
        UPDATE resource_grants SET state='revoked',updated_at=clock_timestamp()
        WHERE organization_id=:org AND membership_id=:member AND project_id=:project
          AND resource_id=ANY(CAST(:ids AS uuid[])) AND state='active' RETURNING resource_id,state
    """,
            {**params, "ids": removals},
        )
        if removals
        else []
    )
    return sorted(added + removed, key=lambda item: str(item["resource_id"]))


@journaled(
    "grant.diff",
    lambda actor, organization_id, membership_id, project_id, body, key, version: (
        organization_id,
        key,
        {"membership_id": membership_id, "project_id": project_id, "expected_version": version, **body},
    ),
)
def apply_diff(
    actor: Any, organization_id: str, membership_id: str, project_id: str, body: dict, key: str, version: int
) -> dict:
    additions = sorted(str(value) for value in body["add"])
    removals = sorted(str(value) for value in body["remove"])
    if (
        set(additions) & set(removals)
        or len(set(additions)) != len(additions)
        or len(set(removals)) != len(removals)
    ):
        raise AppError(422, "validation_error", "Grant additions and removals must be unique and disjoint.")
    payload = {"membership_id": membership_id, "project_id": project_id, "expected_version": version, **body}
    resources = sorted(set(additions + removals))
    _preflight_grants(actor, organization_id, project_id, resources)
    with db.transaction() as conn:
        db.lock_resources(conn, resources)
        db.lock_org(conn, organization_id, exclusive=True)
        require_member(conn, actor, organization_id, manager=True)
        stored = receipt(conn, actor, organization_id, "grant.diff", key, payload)
        if stored is not None:
            return stored
        enforce_writable(conn, organization_id)
        project = require_project(conn, organization_id, project_id)
        _require_entitlement_pairs(conn, organization_id, project_id, resources)
        member = _target_membership(conn, organization_id, membership_id)
        check_version(member["access_version"], version)
        _validate_additions(conn, organization_id, project_id, member, project, additions)
        changed = _change_grants(conn, organization_id, membership_id, project_id, additions, removals)
        if changed:
            updated = db.row(
                conn,
                """
                UPDATE memberships SET access_version=access_version+1
                WHERE organization_id=:org AND id=:member RETURNING access_version
            """,
                {"org": organization_id, "member": membership_id},
            )
            assert updated is not None
            member["access_version"] = updated["access_version"]
            audit(
                conn,
                actor,
                organization_id,
                "grants.changed",
                "membership",
                membership_id,
                {
                    "project_id": project_id,
                    "changed_grants": changed,
                    "reason": body["reason"],
                    "access_version": member["access_version"],
                },
            )
        response = serialize(
            {
                "membership_id": membership_id,
                "project_id": project_id,
                "access_version": member["access_version"],
                "changed_grants": changed,
            }
        )
        save_receipt(conn, actor, organization_id, "grant.diff", key, payload, response)
        return response


@journaled(
    "report.create",
    lambda actor, organization_id, project_id, body, key: (
        organization_id,
        key,
        {"project_id": project_id, **body},
    ),
)
def create_report(actor: Any, organization_id: str, project_id: str, body: dict, key: str) -> dict:
    resources = sorted(str(value) for value in body["resource_ids"])
    payload = {"project_id": project_id, **body}
    _preflight_use(actor, organization_id, project_id, resources)
    with db.transaction() as conn:
        db.lock_resources(conn, resources)
        db.lock_org(conn, organization_id, exclusive=False)
        require_member(conn, actor, organization_id)
        stored = receipt(conn, actor, organization_id, "report.create", key, payload)
        if stored is not None:
            authorize_resources(conn, actor, organization_id, project_id, resources)
            return stored
        enforce_writable(conn, organization_id)
        authorize_resources(conn, actor, organization_id, project_id, resources)
        report_id = str(uuid4())
        conn.execute(
            text("""
            INSERT INTO report_configs(id,organization_id,project_id,name,created_by)
            VALUES(:id,:org,:project,:name,:user)
        """),
            {
                "id": report_id,
                "org": organization_id,
                "project": project_id,
                "name": body["name"],
                "user": str(actor_value(actor, "user_id")),
            },
        )
        conn.execute(
            text("""
            INSERT INTO report_resource_refs(organization_id,project_id,report_config_id,resource_id)
            SELECT :org,:project,:report,unnest(CAST(:resources AS uuid[]))
        """),
            {"org": organization_id, "project": project_id, "report": report_id, "resources": resources},
        )
        response = {
            "id": report_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "name": body["name"],
            "resource_ids": resources,
        }
        audit(
            conn,
            actor,
            organization_id,
            "report.created",
            "report_config",
            report_id,
            {"project_id": project_id, "resource_count": len(resources)},
        )
        save_receipt(conn, actor, organization_id, "report.create", key, payload, response, 201)
        return response


def get_report(actor: Any, organization_id: str, project_id: str, report_id: str) -> dict:
    with db.transaction() as conn:
        require_member(conn, actor, organization_id)
        require_project(conn, organization_id, project_id)
        report = db.row(
            conn,
            """
            SELECT id,organization_id,project_id,name FROM report_configs
            WHERE organization_id=:org AND project_id=:project AND id=:report
        """,
            {"org": organization_id, "project": project_id, "report": report_id},
        )
        if not report:
            raise AppError(404, "report_not_found", "Report configuration was not found.")
        refs = db.rows(
            conn,
            """
            SELECT resource_id FROM report_resource_refs WHERE organization_id=:org AND project_id=:project
              AND report_config_id=:report ORDER BY resource_id
        """,
            {"org": organization_id, "project": project_id, "report": report_id},
        )
        resources = [str(item["resource_id"]) for item in refs]
        db.lock_resources(conn, resources)
        db.lock_org(conn, organization_id, exclusive=False)
        require_member(conn, actor, organization_id)
        authorize_resources(conn, actor, organization_id, project_id, resources)
        return {**serialize(report), "resource_ids": resources}

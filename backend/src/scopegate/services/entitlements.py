"""Reviewed entitlement transitions revoke dependent access atomically."""

from typing import Any

from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services.common import (
    audit,
    check_version,
    enforce_writable,
    journaled,
    receipt,
    request_hash,
    require_project,
    save_receipt,
    serialize,
)


def _impact(conn: Any, organization_id: str, project_id: str, resource_id: str, desired: str) -> dict:
    entitlement = db.row(
        conn,
        """
        SELECT status,entitlement_version FROM project_resources
        WHERE organization_id=:org AND project_id=:project AND resource_id=:resource
    """,
        {"org": organization_id, "project": project_id, "resource": resource_id},
    )
    params = {"org": organization_id, "project": project_id, "resource": resource_id}
    grants = (
        db.rows(
            conn,
            """
        SELECT g.membership_id,m.access_version FROM resource_grants g
        JOIN memberships m ON m.organization_id=g.organization_id AND m.id=g.membership_id
        WHERE g.organization_id=:org AND g.project_id=:project AND g.resource_id=:resource
          AND g.state='active' ORDER BY g.membership_id LIMIT 501
    """,
            params,
        )
        if desired == "disabled"
        else []
    )
    invitations = (
        db.rows(
            conn,
            """
        SELECT i.id FROM invitations i JOIN invitation_resources ir
          ON ir.organization_id=i.organization_id AND ir.invitation_id=i.id
        WHERE ir.organization_id=:org AND ir.project_id=:project AND ir.resource_id=:resource
          AND i.state='pending' ORDER BY i.id LIMIT 201
    """,
            params,
        )
        if desired == "disabled"
        else []
    )
    memberships = {str(item["membership_id"]) for item in grants}
    if len(grants) > 500 or len(memberships) > 200 or len(invitations) > 200:
        raise AppError(
            409, "entitlement_impact_too_large", "Impact exceeds the reviewed atomic transition limits."
        )
    revision = entitlement["entitlement_version"] if entitlement else 0
    fingerprint = {
        "organization_id": organization_id,
        "project_id": project_id,
        "resource_id": resource_id,
        "desired_status": desired,
        "version": revision,
        "status": entitlement["status"] if entitlement else None,
        "grants": grants,
        "invitations": invitations,
    }
    return {
        "entitlement_version": revision,
        "desired_status": desired,
        "affected_memberships": len(memberships),
        "active_grants": len(grants),
        "pending_invitations": len(invitations),
        "impact_token": request_hash(fingerprint),
    }


def _require_resource(conn: Any, resource_id: str, desired: str) -> None:
    resource = db.row(conn, "SELECT status FROM resources WHERE id=:id", {"id": resource_id})
    if not resource:
        raise AppError(404, "resource_not_found", "Resource was not found.")
    if desired == "active" and resource["status"] != "published":
        raise AppError(409, "resource_unpublished", "An archived resource cannot be entitled.")


def get_impact(actor: Any, organization_id: str, project_id: str, resource_id: str, desired: str) -> dict:
    with db.transaction() as conn:
        db.lock_resources(conn, [resource_id])
        db.lock_org(conn, organization_id, exclusive=False)
        require_project(conn, organization_id, project_id)
        _require_resource(conn, resource_id, desired)
        return _impact(conn, organization_id, project_id, resource_id, desired)


def _revoke_dependents(conn: Any, organization_id: str, project_id: str, resource_id: str) -> dict:
    params = {"org": organization_id, "project": project_id, "resource": resource_id}
    # Organization ownership serializes cooperating writers. Explicit sorted row
    # locks make the affected aggregate and invitation ordering visible as well.
    db.rows(
        conn,
        """
        SELECT m.id FROM memberships m WHERE m.organization_id=:org AND EXISTS(
          SELECT 1 FROM resource_grants g WHERE g.organization_id=m.organization_id
          AND g.membership_id=m.id AND g.project_id=:project AND g.resource_id=:resource AND g.state='active')
        ORDER BY m.id FOR UPDATE
    """,
        params,
    )
    invitations = db.rows(
        conn,
        """
        SELECT i.id FROM invitations i WHERE i.organization_id=:org AND i.state='pending' AND EXISTS(
          SELECT 1 FROM invitation_resources ir WHERE ir.organization_id=i.organization_id
          AND ir.invitation_id=i.id AND ir.project_id=:project AND ir.resource_id=:resource)
        ORDER BY i.id FOR UPDATE
    """,
        params,
    )
    grants = db.rows(
        conn,
        """
        UPDATE resource_grants SET state='revoked',updated_at=clock_timestamp()
        WHERE organization_id=:org AND project_id=:project AND resource_id=:resource AND state='active'
        RETURNING membership_id
    """,
        params,
    )
    members = sorted({str(item["membership_id"]) for item in grants})
    if members:
        conn.execute(
            text("""
            UPDATE memberships SET access_version=access_version+1
            WHERE organization_id=:org AND id=ANY(CAST(:members AS uuid[]))
        """),
            {"org": organization_id, "members": members},
        )
    invitation_ids = [str(item["id"]) for item in invitations]
    if invitation_ids:
        conn.execute(
            text("""
            UPDATE invitations SET state='revoked' WHERE organization_id=:org AND id=ANY(CAST(:ids AS uuid[]))
        """),
            {"org": organization_id, "ids": invitation_ids},
        )
    return {
        "active_grants_revoked": len(grants),
        "memberships_advanced": len(members),
        "invitations_revoked": len(invitations),
    }


@journaled(
    "entitlement.set",
    lambda actor, organization_id, project_id, resource_id, body, key, version: (
        organization_id,
        key,
        {"project_id": project_id, "resource_id": resource_id, "expected_version": version, **body},
    ),
)
def set_entitlement(
    actor: Any, organization_id: str, project_id: str, resource_id: str, body: dict, key: str, version: int
) -> dict:
    payload = {"project_id": project_id, "resource_id": resource_id, "expected_version": version, **body}
    with db.transaction() as conn:
        db.lock_resources(conn, [resource_id])
        db.lock_org(conn, organization_id, exclusive=True)
        require_project(conn, organization_id, project_id)
        stored = receipt(conn, actor, organization_id, "entitlement.set", key, payload)
        if stored is not None:
            return stored
        _require_resource(conn, resource_id, body["status"])
        enforce_writable(conn, organization_id)
        impact = _impact(conn, organization_id, project_id, resource_id, body["status"])
        check_version(impact["entitlement_version"], version, "entitlement_version_conflict")
        if impact["impact_token"] != body["impact_token"]:
            raise AppError(
                412, "entitlement_impact_conflict", "The reviewed impact changed. Preview it again."
            )
        current = db.row(
            conn,
            """
            SELECT status,entitlement_version FROM project_resources
            WHERE organization_id=:org AND project_id=:project AND resource_id=:resource
        """,
            {"org": organization_id, "project": project_id, "resource": resource_id},
        )
        changed = current is None or current["status"] != body["status"]
        summary = (
            _revoke_dependents(conn, organization_id, project_id, resource_id)
            if changed and body["status"] == "disabled"
            else {}
        )
        result = db.row(
            conn,
            """
            INSERT INTO project_resources(organization_id,project_id,resource_id,status,entitlement_version)
            VALUES(:org,:project,:resource,:status,1)
            ON CONFLICT(organization_id,project_id,resource_id) DO UPDATE
            SET status=EXCLUDED.status,entitlement_version=project_resources.entitlement_version+:advance,
                updated_at=CASE WHEN :advance=1 THEN clock_timestamp() ELSE project_resources.updated_at END
            RETURNING project_id,resource_id,status,entitlement_version
        """,
            {
                "org": organization_id,
                "project": project_id,
                "resource": resource_id,
                "status": body["status"],
                "advance": int(changed),
            },
        )
        response = serialize(result)
        if changed:
            audit(
                conn,
                actor,
                organization_id,
                "entitlement.changed",
                "project_resource",
                f"{project_id}:{resource_id}",
                {"status": body["status"], "reason": body["reason"], **summary},
            )
        save_receipt(conn, actor, organization_id, "entitlement.set", key, payload, response)
        return response

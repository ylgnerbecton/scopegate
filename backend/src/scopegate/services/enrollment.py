"""Finite verified-recipient enrollment, with atomic scoped grants and receipts."""

from __future__ import annotations

import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import delivery
from scopegate.services.common import (
    audit,
    cursor_uuid,
    enforce_writable,
    journaled,
    membership_view,
    page,
    receipt,
    require_member,
    save_receipt,
    serialize,
)
from scopegate.services.identity import normalize_email, token_hash
from scopegate.services.invariants import required_row

INVITATION_FIELDS = ("id", "organization_id", "recipient_email", "state", "delivery_state", "expires_at")


def invitation_view(conn, invitation: dict) -> dict:
    latest = db.row(
        conn,
        "SELECT state FROM outbox_messages WHERE invitation_id=:id ORDER BY created_at DESC,id DESC LIMIT 1",
        {"id": str(invitation["id"])},
    )
    state = invitation["state"]
    if state == "pending" and invitation["expires_at"] <= db.clock(conn):
        state = "expired"
    return serialize(
        {
            **{key: invitation[key] for key in INVITATION_FIELDS if key not in {"state", "delivery_state"}},
            "state": state,
            "delivery_state": latest["state"] if latest else "pending",
        }
    )


def _selection(conn, organization_id: str, resources: list[dict]) -> list[dict]:
    unique = {(str(item["project_id"]), str(item["resource_id"])) for item in resources}
    if len(unique) != len(resources) or not 1 <= len(resources) <= 100:
        raise AppError(422, "validation_error", "Select 1 to 100 distinct project resources.")
    selected = []
    for project_id, resource_id in sorted(unique):
        item = db.row(
            conn,
            """
            SELECT pr.*,p.status AS project_status,r.status AS resource_status
            FROM project_resources pr JOIN projects p ON p.id=pr.project_id AND p.organization_id=pr.organization_id
            JOIN resources r ON r.id=pr.resource_id
            WHERE pr.organization_id=:org AND pr.project_id=:project AND pr.resource_id=:resource
        """,
            {"org": str(organization_id), "project": project_id, "resource": resource_id},
        )
        if (
            not item
            or item["status"] != "active"
            or item["project_status"] != "active"
            or item["resource_status"] != "published"
        ):
            raise AppError(
                409, "selection_unavailable", "A selected project resource is no longer available."
            )
        selected.append({"project_id": project_id, "resource_id": resource_id})
    return selected


def list_invitations(actor: dict, organization_id: str, limit: int = 25, cursor: str | None = None) -> dict:
    scope = ["invitations", str(organization_id), actor["user_id"]]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        items = db.rows(
            conn,
            """
            SELECT * FROM invitations WHERE organization_id=:org
              AND (CAST(:marker AS uuid) IS NULL OR id>CAST(:marker AS uuid)) ORDER BY id LIMIT :limit
        """,
            {"org": str(organization_id), "marker": marker, "limit": limit + 1},
        )
        items = [invitation_view(conn, item) for item in items]
    return page(items, limit, scope, cursor)


@journaled(
    "invitation.create",
    lambda actor, organization_id, body, key: (
        str(organization_id),
        key,
        {"organization_id": str(organization_id), **serialize(body)},
    ),
)
def create_invitation(actor: dict, organization_id: str, body: dict, key: str) -> dict:
    payload = {"organization_id": str(organization_id), **serialize(body)}
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        _selection(conn, organization_id, body["resources"])
        db.lock_resources(conn, [str(item["resource_id"]) for item in body["resources"]])
        db.lock_org(conn, organization_id)
        require_member(conn, actor, organization_id, manager=True)
        enforce_writable(conn, organization_id)
        stored = receipt(conn, actor, organization_id, "invitation.create", key, payload)
        if stored:
            return stored
        selection = _selection(conn, organization_id, body["resources"])
        pending = db.row(
            conn,
            """
            SELECT id FROM invitations WHERE organization_id=:org AND recipient_email_normalized=:email
              AND state='pending' AND expires_at>clock_timestamp() LIMIT 1
        """,
            {"org": str(organization_id), "email": normalize_email(body["email"])},
        )
        if pending:
            raise AppError(
                409, "invitation_exists", "A pending invitation already exists for this recipient."
            )
        token = secrets.token_urlsafe(32)
        invitation_id = str(uuid4())
        invitation = required_row(
            conn,
            """
            INSERT INTO invitations(id,organization_id,recipient_email,token_hash,created_by,expires_at)
            VALUES(:id,:org,:email,:hash,:user,clock_timestamp()+(:hours*interval '1 hour')) RETURNING *
        """,
            {
                "id": invitation_id,
                "org": str(organization_id),
                "email": body["email"].strip(),
                "hash": token_hash(token),
                "user": actor["user_id"],
                "hours": body.get("expires_in_hours", 72),
            },
        )
        for item in selection:
            conn.execute(
                text("""
                INSERT INTO invitation_resources(organization_id,invitation_id,project_id,resource_id)
                VALUES(:org,:id,:project,:resource)
            """),
                {
                    "org": str(organization_id),
                    "id": invitation_id,
                    "project": item["project_id"],
                    "resource": item["resource_id"],
                },
            )
        delivery.enqueue(conn, organization_id, invitation_id, body["email"].strip(), token)
        audit(
            conn,
            actor,
            organization_id,
            "invitation.created",
            "invitation",
            invitation_id,
            {"resource_count": len(selection)},
        )
        response = invitation_view(conn, invitation)
        save_receipt(conn, actor, organization_id, "invitation.create", key, payload, response, 201)
        return response


def change_invitation(actor: dict, organization_id: str, invitation_id: str, key: str, action: str) -> dict:
    payload = {"organization_id": str(organization_id), "invitation_id": str(invitation_id), "action": action}
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        resources = db.rows(
            conn,
            "SELECT project_id,resource_id FROM invitation_resources WHERE organization_id=:org AND invitation_id=:id",
            {"org": str(organization_id), "id": str(invitation_id)},
        )
        if action == "resend":
            _selection(conn, organization_id, resources)
            db.lock_resources(conn, [str(item["resource_id"]) for item in resources])
        db.lock_org(conn, organization_id)
        require_member(conn, actor, organization_id, manager=True)
        enforce_writable(conn, organization_id)
        stored = receipt(conn, actor, organization_id, "invitation." + action, key, payload)
        if stored:
            return stored
        invitation = db.row(
            conn,
            "SELECT * FROM invitations WHERE organization_id=:org AND id=:id FOR UPDATE",
            {"org": str(organization_id), "id": str(invitation_id)},
        )
        if not invitation:
            raise AppError(404, "invitation_not_found", "Invitation was not found.")
        if invitation["state"] != "pending" or invitation["expires_at"] <= db.clock(conn):
            raise AppError(409, "invitation_unavailable", "Only a pending unexpired invitation can change.")
        invitation = _change_pending_invitation(
            conn, organization_id, invitation_id, invitation, resources, action
        )
        audit(
            conn,
            actor,
            organization_id,
            "invitation." + ("resent" if action == "resend" else "revoked"),
            "invitation",
            invitation_id,
            {},
        )
        response = invitation_view(conn, invitation)
        save_receipt(
            conn,
            actor,
            organization_id,
            "invitation." + action,
            key,
            payload,
            response,
            201 if action == "resend" else 200,
        )
        return response


def _change_pending_invitation(
    conn, organization_id: str, invitation_id: str, invitation: dict, resources: list[dict], action: str
) -> dict:
    if action == "resend":
        _selection(conn, organization_id, resources)
        token = secrets.token_urlsafe(32)
        invitation = required_row(
            conn,
            "UPDATE invitations SET token_hash=:hash WHERE id=:id RETURNING *",
            {"id": str(invitation_id), "hash": token_hash(token)},
        )
        delivery.enqueue(conn, organization_id, invitation_id, invitation["recipient_email"], token)
    elif action == "revoke":
        invitation = required_row(
            conn,
            "UPDATE invitations SET state='revoked' WHERE id=:id RETURNING *",
            {"id": str(invitation_id)},
        )
    else:
        raise ValueError("Unsupported invitation transition")
    return invitation


def _session_claims(conn, actor: dict, now) -> dict:
    if conn is None or not actor.get("session_id"):
        return actor
    session = db.row(
        conn,
        "SELECT verified_email,email_verified,authenticated_at FROM sessions WHERE id=:id AND user_id=:user AND revoked_at IS NULL AND expires_at>:now",
        {"id": actor["session_id"], "user": actor["user_id"], "now": now},
    )
    if session is None:
        raise AppError(401, "authentication_required", "The session is no longer active. Sign in again.")
    return {**actor, **session}


def _trusted_recipient(actor: dict, invitation: dict | None, now, conn=None) -> dict:
    actor = _session_claims(conn, actor, now)
    if (
        not invitation
        or not actor.get("email_verified")
        or not actor.get("verified_email")
        or normalize_email(actor["verified_email"]) != invitation["recipient_email_normalized"]
    ):
        raise AppError(404, "invitation_not_found", "Invitation was not found.")
    authenticated_at = actor.get("authenticated_at")
    if (
        not authenticated_at
        or authenticated_at > now + timedelta(seconds=10)
        or now - authenticated_at > timedelta(minutes=15)
    ):
        raise AppError(
            401, "reauthentication_required", "Sign in again before reviewing or accepting this invitation."
        )

    return invitation


def _pending(invitation: dict, now) -> None:
    if invitation["state"] != "pending" or invitation["expires_at"] <= now:
        raise AppError(410, "invitation_unavailable", "This invitation is no longer available.")


def preview(actor: dict, token: str) -> dict:
    with db.transaction() as conn:
        invitation = db.row(
            conn, "SELECT * FROM invitations WHERE token_hash=:hash", {"hash": token_hash(token)}
        )
        now = db.clock(conn)
        invitation = _trusted_recipient(actor, invitation, now, conn)
        _pending(invitation, now)
        organization = required_row(
            conn,
            "SELECT id,name,status FROM organizations WHERE id=:id",
            {"id": str(invitation["organization_id"])},
        )
        if organization["status"] != "active":
            raise AppError(409, "selection_unavailable", "The organization is unavailable.")
        selected = db.rows(
            conn,
            """
            SELECT ir.project_id,ir.resource_id,p.name AS project_name,l.title AS resource_title,r.external_key
            FROM invitation_resources ir JOIN projects p ON p.id=ir.project_id AND p.organization_id=ir.organization_id
            JOIN resources r ON r.id=ir.resource_id
            LEFT JOIN resource_localizations l ON l.resource_id=r.id AND l.locale='en'
            WHERE ir.organization_id=:org AND ir.invitation_id=:id ORDER BY ir.project_id,ir.resource_id
        """,
            {"org": str(invitation["organization_id"]), "id": str(invitation["id"])},
        )
        _selection(conn, str(invitation["organization_id"]), selected)
        return serialize(
            {
                "organization": organization,
                "recipient_email": invitation["recipient_email"],
                "expires_at": invitation["expires_at"],
                "resources": selected,
            }
        )


def _accept_binding(actor: dict, token: str, key: str):
    with db.transaction() as conn:
        invitation = db.row(
            conn, "SELECT * FROM invitations WHERE token_hash=:hash", {"hash": token_hash(token)}
        )
        invitation = _trusted_recipient(actor, invitation, db.clock(conn), conn)
    return (
        str(invitation["organization_id"]),
        key,
        {"invitation_id": str(invitation["id"]), "token_hash": token_hash(token)},
    )


@journaled("invitation.accept", _accept_binding)
def accept(actor: dict, token: str, key: str) -> dict:
    with db.transaction() as conn:
        invitation = db.row(
            conn, "SELECT * FROM invitations WHERE token_hash=:hash", {"hash": token_hash(token)}
        )
        invitation = _trusted_recipient(actor, invitation, db.clock(conn), conn)
        organization_id = str(invitation["organization_id"])
        invitation_id = str(invitation["id"])
        selected = db.rows(
            conn,
            "SELECT project_id,resource_id FROM invitation_resources WHERE organization_id=:org AND invitation_id=:id",
            {"org": organization_id, "id": invitation_id},
        )
        _selection(conn, organization_id, selected)
        db.lock_resources(conn, [str(item["resource_id"]) for item in selected])
        db.lock_org(conn, organization_id)
        organization = required_row(
            conn, "SELECT status FROM organizations WHERE id=:org", {"org": organization_id}
        )
        if organization["status"] != "active":
            raise AppError(409, "organization_unavailable", "The organization is unavailable.")
        enforce_writable(conn, organization_id)
        membership = db.row(
            conn,
            "SELECT * FROM memberships WHERE organization_id=:org AND user_id=:user FOR UPDATE",
            {"org": organization_id, "user": actor["user_id"]},
        )
        invitation = db.row(
            conn,
            "SELECT * FROM invitations WHERE organization_id=:org AND id=:id FOR UPDATE",
            {"org": organization_id, "id": invitation_id},
        )
        now = db.clock(conn)
        invitation = _trusted_recipient(actor, invitation, now, conn)
        payload = {"invitation_id": invitation_id, "token_hash": token_hash(token)}
        stored = receipt(conn, actor, organization_id, "invitation.accept", key, payload)
        if stored:
            if _member_inactive(membership, now):
                raise AppError(403, "permission_denied", "The current membership is inactive or expired.")
            return stored
        _pending(invitation, now)
        _selection(conn, organization_id, selected)
        membership = _accept_membership(conn, actor, organization_id, membership, now)
        changed = _apply_grants(conn, organization_id, str(membership["id"]), selected)
        if changed:
            membership = required_row(
                conn,
                "UPDATE memberships SET access_version=access_version+1 WHERE id=:id RETURNING *",
                {"id": str(membership["id"])},
            )
        conn.execute(
            text(
                "UPDATE invitations SET state='accepted',accepted_by=:user,accepted_at=clock_timestamp() WHERE id=:id"
            ),
            {"id": invitation_id, "user": actor["user_id"]},
        )
        audit(
            conn,
            actor,
            organization_id,
            "invitation.accepted",
            "invitation",
            invitation_id,
            {
                "membership_id": str(membership["id"]),
                "grant_count": changed,
                "access_version": membership["access_version"],
            },
        )
        contact = required_row(
            conn, "SELECT email,display_name FROM users WHERE id=:id", {"id": actor["user_id"]}
        )
        response = membership_view({**membership, **contact})
        save_receipt(conn, actor, organization_id, "invitation.accept", key, payload, response)
        return response


def _member_inactive(member: dict | None, now) -> bool:
    return member is not None and (
        member["status"] != "active" or (member["expires_at"] is not None and member["expires_at"] <= now)
    )


def _accept_membership(conn, actor: dict, organization_id: str, membership: dict | None, now) -> dict:
    if _member_inactive(membership, now):
        raise AppError(
            409, "membership_inactive", "An access manager must restore this membership before enrollment."
        )
    if membership is not None:
        return membership
    return required_row(
        conn,
        "INSERT INTO memberships(organization_id,user_id) VALUES(:org,:user) RETURNING *",
        {"org": organization_id, "user": actor["user_id"]},
    )


def _apply_grants(conn, organization_id: str, membership_id: str, selected: list[dict]) -> int:
    changed = 0
    for item in selected:
        result = conn.execute(
            text("""
            INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id,state)
            VALUES(:org,:member,:project,:resource,'active')
            ON CONFLICT(organization_id,membership_id,project_id,resource_id) DO UPDATE
            SET state='active',updated_at=clock_timestamp() WHERE resource_grants.state<>'active'
        """),
            {
                "org": organization_id,
                "member": membership_id,
                "project": str(item["project_id"]),
                "resource": str(item["resource_id"]),
            },
        )
        changed += result.rowcount
    return changed

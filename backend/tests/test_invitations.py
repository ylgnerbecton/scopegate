"""Real transaction proofs for invitation, recipient and grant lifecycles."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import delivery, enrollment

pytestmark = pytest.mark.integration


def issue(manager, ids, email="morgan@example.test", resource="market-pulse"):
    org = ids["organizations"]["cedar"]
    body = {
        "email": email,
        "resources": [{"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"][resource]}],
    }
    invitation = enrollment.create_invitation(manager, org, body, str(uuid4()))
    with db.transaction() as conn:
        message = db.row(
            conn, "SELECT * FROM outbox_messages WHERE invitation_id=:id", {"id": invitation["id"]}
        )
    token = delivery.current_payload(message)["accept_url"].partition("#token=")[2]
    return invitation, token, message


def test_new_recipient_atomic_acceptance_and_matching_retry(manager, recipient, ids):
    invitation, token, _ = issue(manager, ids)
    preview = enrollment.preview(recipient, token)
    assert preview["organization"]["id"] == ids["organizations"]["cedar"]
    key = str(uuid4())
    accepted = enrollment.accept(recipient, token, key)
    assert accepted["role"] == "viewer" and accepted["status"] == "active"
    assert enrollment.accept(recipient, token, key) == accepted
    with db.transaction() as conn:
        grants = db.rows(
            conn, "SELECT * FROM resource_grants WHERE membership_id=:id", {"id": accepted["id"]}
        )
        invitation_state = db.row(
            conn, "SELECT state FROM invitations WHERE id=:id", {"id": invitation["id"]}
        )
        audits = db.row(
            conn, "SELECT count(*) AS count FROM audit_events WHERE action='invitation.accepted'", {}
        )
    assert len(grants) == 1 and str(grants[0]["resource_id"]) == ids["resources"]["market-pulse"]
    assert invitation_state["state"] == "accepted" and audits["count"] == 1


def test_existing_manager_is_reused_without_downgrade(manager, ids):
    _, token, _ = issue(manager, ids, "amelia@example.test", "revenue-compass")
    result = enrollment.accept(manager, token, str(uuid4()))
    assert result["id"] == ids["memberships"]["manager"] and result["role"] == "access_manager"


@pytest.mark.parametrize("change", [{"email_verified": False}, {"verified_email": "other@example.test"}])
def test_wrong_or_unverified_recipient_is_concealed(manager, recipient, ids, change):
    _, token, _ = issue(manager, ids)
    with pytest.raises(AppError) as error:
        enrollment.preview({**recipient, **change}, token)
    assert error.value.status == 404
    with pytest.raises(AppError) as error:
        enrollment.accept({**recipient, **change}, token, str(uuid4()))
    assert error.value.status == 404


def test_stale_provider_authentication_cannot_preview_or_accept(manager, recipient, ids):
    _, token, _ = issue(manager, ids)
    stale = {**recipient, "authenticated_at": recipient["authenticated_at"] - timedelta(minutes=16)}
    with pytest.raises(AppError) as error:
        enrollment.preview(stale, token)
    assert error.value.code == "reauthentication_required"
    with pytest.raises(AppError):
        enrollment.accept(stale, token, str(uuid4()))


def test_consumed_token_with_new_key_cannot_repeat(manager, recipient, ids):
    _, token, _ = issue(manager, ids)
    enrollment.accept(recipient, token, str(uuid4()))
    with pytest.raises(AppError) as error:
        enrollment.accept(recipient, token, str(uuid4()))
    assert error.value.status == 410


def test_same_token_acceptance_race_only_one_transition(manager, recipient, ids):
    _, token, _ = issue(manager, ids)
    key = str(uuid4())

    def same_intent(_):
        try:
            return enrollment.accept(recipient, token, key)
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) != "55P03":
                raise
            return "rolled_back_lock_timeout"

    with ThreadPoolExecutor(max_workers=2) as executor:
        initial = list(executor.map(same_intent, range(2)))
    assert any(isinstance(value, dict) for value in initial)
    results = [
        enrollment.accept(recipient, token, key) if value == "rolled_back_lock_timeout" else value
        for value in initial
    ]
    assert results[0] == results[1]
    with db.transaction() as conn:
        assert (
            db.row(conn, "SELECT count(*) AS count FROM audit_events WHERE action='invitation.accepted'")[
                "count"
            ]
            == 1
        )


def test_two_keys_race_is_single_use(manager, recipient, ids):
    _, token, _ = issue(manager, ids)

    keys = [str(uuid4()), str(uuid4())]

    def accept(key):
        try:
            return enrollment.accept(recipient, token, key)
        except AppError as error:
            return error.status
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) != "55P03":
                raise
            return "rolled_back_lock_timeout"

    with ThreadPoolExecutor(max_workers=2) as executor:
        initial = list(executor.map(accept, keys))
    results = [
        accept(key) if value == "rolled_back_lock_timeout" else value
        for key, value in zip(keys, initial, strict=True)
    ]
    assert sum(isinstance(value, dict) for value in results) == 1 and 410 in results


def test_revoked_and_expired_invitation_have_no_membership(manager, recipient, ids, admin_engine):
    invitation, token, _ = issue(manager, ids)
    enrollment.change_invitation(
        manager, ids["organizations"]["cedar"], invitation["id"], str(uuid4()), "revoke"
    )
    with pytest.raises(AppError):
        enrollment.accept(recipient, token, str(uuid4()))
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE invitations SET state='pending',created_at=clock_timestamp()-interval '2 hours',expires_at=clock_timestamp()-interval '1 minute' WHERE id=:id"
            ),
            {"id": invitation["id"]},
        )
    with pytest.raises(AppError):
        enrollment.accept(recipient, token, str(uuid4()))
    with db.transaction() as conn:
        assert not db.row(
            conn, "SELECT id FROM memberships WHERE user_id=:user", {"user": recipient["user_id"]}
        )


def test_entitlement_change_rolls_back_new_membership(manager, recipient, ids, admin_engine):
    _, token, _ = issue(manager, ids)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE project_resources SET status='disabled' WHERE organization_id=:org AND project_id=:project AND resource_id=:resource"
            ),
            {
                "org": ids["organizations"]["cedar"],
                "project": ids["projects"]["harbor"],
                "resource": ids["resources"]["market-pulse"],
            },
        )
    with pytest.raises(AppError) as error:
        enrollment.accept(recipient, token, str(uuid4()))
    assert error.value.code == "selection_unavailable"
    with db.transaction() as conn:
        assert not db.row(
            conn, "SELECT id FROM memberships WHERE user_id=:user", {"user": recipient["user_id"]}
        )


def test_archived_resource_rolls_back_acceptance(manager, recipient, ids, admin_engine):
    _, token, _ = issue(manager, ids)
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE resources SET status='archived' WHERE id=:id"),
            {"id": ids["resources"]["market-pulse"]},
        )
    with pytest.raises(AppError):
        enrollment.accept(recipient, token, str(uuid4()))


def test_invitation_cannot_restore_suspended_member(manager, viewer, ids, admin_engine):
    _, token, _ = issue(manager, ids, "jonah@example.test", "audience-atlas")
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE memberships SET status='suspended' WHERE id=:id"),
            {"id": ids["memberships"]["viewer"]},
        )
    with pytest.raises(AppError) as error:
        enrollment.accept(viewer, token, str(uuid4()))
    assert error.value.code == "membership_inactive"


def test_resend_invalidates_old_token_and_receipt_is_stable(manager, recipient, ids):
    invitation, old_token, _ = issue(manager, ids)
    key = str(uuid4())
    result = enrollment.change_invitation(
        manager, ids["organizations"]["cedar"], invitation["id"], key, "resend"
    )
    assert (
        enrollment.change_invitation(manager, ids["organizations"]["cedar"], invitation["id"], key, "resend")
        == result
    )
    with pytest.raises(AppError):
        enrollment.preview(recipient, old_token)
    with db.transaction() as conn:
        assert (
            db.row(
                conn,
                "SELECT count(*) AS count FROM outbox_messages WHERE invitation_id=:id",
                {"id": invitation["id"]},
            )["count"]
            == 2
        )


def test_viewer_cannot_issue_or_list_and_cross_org_is_concealed(viewer, manager, ids):
    body = {
        "email": "morgan@example.test",
        "resources": [
            {"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"]}
        ],
    }
    with pytest.raises(AppError) as error:
        enrollment.create_invitation(viewer, ids["organizations"]["cedar"], body, str(uuid4()))
    assert error.value.status == 403
    with pytest.raises(AppError) as error:
        enrollment.list_invitations(manager, ids["organizations"]["birch"])
    assert error.value.status == 404


def test_duplicate_pending_recipient_does_not_create_second_outbox(manager, ids):
    issue(manager, ids)
    with pytest.raises(AppError) as error:
        issue(manager, ids)
    assert error.value.code == "invitation_exists"

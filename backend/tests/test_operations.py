"""Controlled restore and independent journal failure rehearsals."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from scopegate import db, journal
from scopegate.errors import AppError
from scopegate.services import access, recovery
from scopegate.services.identity import create_session

pytestmark = [pytest.mark.integration, pytest.mark.operations]


def revoke(manager, ids):
    body = {
        "add": [],
        "remove": [ids["resources"]["market-pulse"]],
        "reason": "Reviewed synthetic revocation",
    }
    return access.apply_diff(
        manager,
        ids["organizations"]["cedar"],
        ids["memberships"]["viewer"],
        ids["projects"]["harbor"],
        body,
        str(uuid4()),
        1,
    )


def test_compatible_rollback_keeps_target_authority_and_revocation(manager, viewer, ids):
    revoke(manager, ids)
    with db.transaction() as conn:
        organization = db.row(
            conn, "SELECT access_mode FROM organizations WHERE id=:id", {"id": ids["organizations"]["cedar"]}
        )
        grant = db.row(
            conn,
            "SELECT state FROM resource_grants WHERE membership_id=:member AND resource_id=:resource",
            {"member": ids["memberships"]["viewer"], "resource": ids["resources"]["market-pulse"]},
        )
    assert organization["access_mode"] == "target" and grant["state"] == "revoked"
    with pytest.raises(AppError):
        access.get_report(viewer, ids["organizations"]["cedar"], ids["projects"]["harbor"], str(uuid4()))


def test_restore_replays_revocation_before_any_tenant_reopens(manager, viewer, ids, admin_engine):
    org = ids["organizations"]["cedar"]
    revoke(manager, ids)
    marker = recovery.begin_restore(org, 1)
    assert marker["minimum_epoch"] == 2
    # Restore the earlier policy rows, as an older database snapshot would do.
    # The independent marker and journal remain outside that database snapshot.
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE resource_grants SET state='active' WHERE membership_id=:member AND resource_id=:resource"
            ),
            {"member": ids["memberships"]["viewer"], "resource": ids["resources"]["market-pulse"]},
        )
        conn.execute(
            text("UPDATE memberships SET access_version=1 WHERE id=:id"), {"id": ids["memberships"]["viewer"]}
        )
        conn.execute(text("UPDATE organizations SET status='active' WHERE id=:org"), {"org": org})
        conn.execute(text("DELETE FROM command_receipts WHERE organization_id=:org"), {"org": org})
    with pytest.raises(AppError) as error:
        recovery.assert_open(org)
    assert error.value.status == 503
    manifest = recovery.inspect_journal(org)
    result = recovery.reconcile_restore(org, manifest["journal_hash"])
    assert result["opened"] and result["restriction_count"] == 1
    recovery.assert_open(org)
    with db.transaction() as conn:
        grant = db.row(
            conn,
            "SELECT state FROM resource_grants WHERE membership_id=:member AND resource_id=:resource",
            {"member": ids["memberships"]["viewer"], "resource": ids["resources"]["market-pulse"]},
        )
    assert grant["state"] == "revoked"


def test_uncertain_revocation_denies_and_requires_explicit_review(manager, ids):
    org = ids["organizations"]["cedar"]
    delta = {
        "membership_id": ids["memberships"]["viewer"],
        "project_id": ids["projects"]["harbor"],
        "expected_version": 1,
        "add": [],
        "remove": [ids["resources"]["market-pulse"]],
    }
    reference = journal.prepare(
        manager["actor_key"], org, "grant.diff", str(uuid4()), delta, safe_delta=delta
    )
    recovery.begin_restore(org, 1)
    manifest = recovery.inspect_journal(org)
    result = recovery.reconcile_restore(org, manifest["journal_hash"])
    assert not result["opened"] and reference in result["unresolved_references"]
    with db.transaction() as conn:
        assert (
            db.row(
                conn,
                "SELECT state FROM resource_grants WHERE membership_id=:id AND resource_id=:resource",
                {"id": ids["memberships"]["viewer"], "resource": ids["resources"]["market-pulse"]},
            )["state"]
            == "revoked"
        )
    result = recovery.reconcile_restore(org, manifest["journal_hash"], confirmed_denials=[reference])
    assert result["opened"]


def test_unresolved_addition_cannot_be_guessed_during_restore(manager, ids):
    org = ids["organizations"]["cedar"]
    delta = {
        "membership_id": ids["memberships"]["viewer"],
        "project_id": ids["projects"]["harbor"],
        "expected_version": 1,
        "add": [ids["resources"]["audience-atlas"]],
        "remove": [],
    }
    reference = journal.prepare(
        manager["actor_key"], org, "grant.diff", str(uuid4()), delta, safe_delta=delta
    )
    journal.outcome(reference, "committed", {"synthetic": True})
    recovery.begin_restore(org, 1)
    manifest = recovery.inspect_journal(org)
    result = recovery.reconcile_restore(org, manifest["journal_hash"])
    assert not result["opened"] and reference in result["unresolved_references"]
    with db.transaction() as conn:
        assert not db.row(
            conn,
            "SELECT state FROM resource_grants WHERE membership_id=:id AND resource_id=:resource",
            {"id": ids["memberships"]["viewer"], "resource": ids["resources"]["audience-atlas"]},
        )


def test_catalog_rollback_keeps_restore_closed(manager, ids, admin_engine):
    org = ids["organizations"]["cedar"]
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE resources SET status='archived' WHERE id=:resource"),
            {"resource": ids["resources"]["market-pulse"]},
        )
    recovery.begin_restore(org, 1)
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE resources SET status='published' WHERE id=:resource"),
            {"resource": ids["resources"]["market-pulse"]},
        )
    manifest = recovery.inspect_journal(org)
    result = recovery.reconcile_restore(org, manifest["journal_hash"])
    assert not result["opened"] and "catalog_manifest_changed" in result["unresolved_references"]


def test_restore_revokes_session_and_pending_delivery(manager, ids, settings):
    org = ids["organizations"]["cedar"]
    from scopegate.services import enrollment

    enrollment.create_invitation(
        manager,
        org,
        {
            "email": "morgan@example.test",
            "resources": [
                {"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"]}
            ],
        },
        str(uuid4()),
    )
    create_session(
        {
            "iss": settings.oidc_issuer,
            "sub": "viewer-cedar",
            "email": "jonah@example.test",
            "name": "Jonah Reed",
            "email_verified": True,
            "auth_time": manager["authenticated_at"].timestamp(),
        }
    )
    recovery.begin_restore(org, 1)
    manifest = recovery.inspect_journal(org)
    result = recovery.reconcile_restore(org, manifest["journal_hash"])
    assert result["opened"]
    with db.transaction() as conn:
        assert db.row(conn, "SELECT revoked_at FROM sessions LIMIT 1")["revoked_at"] is not None
        assert db.row(conn, "SELECT state FROM invitations LIMIT 1")["state"] == "revoked"
        outbox = db.row(conn, "SELECT state,encrypted_payload FROM outbox_messages LIMIT 1")
    assert outbox["state"] == "failed" and outbox["encrypted_payload"] is None


def test_changed_review_manifest_cannot_reopen_and_no_effects(manager, ids):
    org = ids["organizations"]["cedar"]
    recovery.begin_restore(org, 1)
    with pytest.raises(AppError) as error:
        recovery.reconcile_restore(org, "0" * 64)
    assert error.value.status == 412
    with pytest.raises(AppError):
        recovery.assert_open(org)


def test_unknown_operation_keeps_restore_closed_even_if_denial_supplied(manager, ids):
    org = ids["organizations"]["cedar"]
    reference = journal.prepare(
        manager["actor_key"], org, "unsupported.permission", str(uuid4()), {}, safe_delta={}
    )
    journal.outcome(reference, "committed", {})
    recovery.begin_restore(org, 1)
    manifest = recovery.inspect_journal(org)
    result = recovery.reconcile_restore(org, manifest["journal_hash"], confirmed_denials=[reference])
    assert not result["opened"]

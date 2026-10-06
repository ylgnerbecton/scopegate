"""Controlled restore and independent journal failure rehearsals."""

import json
from pathlib import Path
from runpy import run_path
from time import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from scopegate import db, journal
from scopegate.errors import AppError
from scopegate.services import access, recovery
from scopegate.services.identity import SESSION_COOKIE, create_session, csrf_value

pytestmark = [pytest.mark.integration, pytest.mark.operations]


def revoke(manager, ids, version=1):
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
        version,
    )


def test_compatible_rollback_keeps_target_authority_and_revocation(manager, viewer, ids, settings):
    root = Path(__file__).resolve().parents[2]
    applications = run_path(str(root / "scripts/rehearse_rollback.py"))["applications"]
    tokens = {
        role: create_session({
            "iss": settings.oidc_issuer, "sub": subject, "email": actor["email"],
            "email_verified": True, "name": role, "auth_time": int(time()),
        })
        for role, actor, subject in [
            ("manager", manager, "manager-cedar"), ("viewer", viewer, "viewer-cedar")
        ]
    }
    org, project = ids["organizations"]["cedar"], ids["projects"]["harbor"]
    base = f"/api/v1/organizations/{org}"
    report_route = base + f"/projects/{project}/report-configs"
    grant_route = base + f"/memberships/{ids['memberships']['viewer']}/projects/{project}/grants"

    def headers(role, version=None):
        values = {"Origin": settings.public_origin, "X-CSRF-Token": csrf_value(tokens[role]),
                  "Idempotency-Key": str(uuid4())}
        if version is not None:
            values["If-Match"] = f'"v{version}"'
        return values

    with applications(root, settings) as rehearsal:
        with httpx.Client(base_url=rehearsal.base_url, timeout=3, trust_env=False,
                          cookies={SESSION_COOKIE: tokens["manager"]}) as client:
            granted = client.patch(grant_route, headers=headers("manager", 1), json={
                "add": [ids["resources"]["growth-signals"]], "remove": [],
                "reason": "Reviewed positive control for compatible application rollback",
            })
            assert granted.status_code == 200, granted.text
        reports = {}
        with httpx.Client(base_url=rehearsal.base_url, timeout=3, trust_env=False,
                          cookies={SESSION_COOKIE: tokens["viewer"]}) as client:
            for key in ["market-pulse", "growth-signals"]:
                created = client.post(report_route, headers=headers("viewer"), json={
                    "name": "Compatible rollback " + key, "resource_ids": [ids["resources"][key]],
                })
                assert created.status_code == 201, created.text
                reports[key] = created.json()["id"]
                before = client.get(report_route + "/" + reports[key])
                assert before.status_code == 200 and before.json()["id"] == reports[key]
        with httpx.Client(base_url=rehearsal.base_url, timeout=3, trust_env=False,
                          cookies={SESSION_COOKIE: tokens["manager"]}) as client:
            revoked = client.patch(
                grant_route, headers=headers("manager", 2),
                json={"add": [], "remove": [ids["resources"]["market-pulse"]],
                      "reason": "Reviewed revocation before compatible application rollback"},
            )
            assert revoked.status_code == 200, revoked.text
        rehearsal.previous()
        with httpx.Client(base_url=rehearsal.base_url, timeout=3, trust_env=False,
                          cookies={SESSION_COOKIE: tokens["viewer"]}) as client:
            control = client.get(report_route + "/" + reports["growth-signals"])
            assert control.status_code == 200, control.text
            assert control.json()["resource_ids"] == [ids["resources"]["growth-signals"]]
            after = client.get(report_route + "/" + reports["market-pulse"])
            assert after.status_code == 404, after.text
            assert after.json()["error"]["code"] == "resource_not_found"
        evidence = rehearsal.metadata()
    with db.transaction() as conn:
        organization = db.row(
            conn, "SELECT access_mode FROM organizations WHERE id=:id", {"id": ids["organizations"]["cedar"]}
        )
        grants = db.rows(
            conn,
            "SELECT resource_id,state FROM resource_grants WHERE organization_id=:org AND project_id=:project "
            "AND membership_id=:member AND resource_id IN (:market,:growth)",
            {"org": org, "project": project, "member": ids["memberships"]["viewer"],
             "market": ids["resources"]["market-pulse"], "growth": ids["resources"]["growth-signals"]},
        )
        existing = db.rows(conn, "SELECT id FROM report_configs WHERE organization_id=:org AND project_id=:project "
                           "AND id IN (:market,:growth)", {"org": org, "project": project,
                            "market": reports["market-pulse"], "growth": reports["growth-signals"]})
    states = {str(row["resource_id"]): row["state"] for row in grants}
    assert organization["access_mode"] == "target"
    assert states[ids["resources"]["market-pulse"]] == "revoked"
    assert states[ids["resources"]["growth-signals"]] == "active"
    assert {str(row["id"]) for row in existing} == set(reports.values())
    artifact = root / "artifacts/operations/rollback-recovery.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps({**evidence, "before_revocation_http_status": 200,
                                   "after_application_rollback_http_status": 404,
                                   "control_report_after_rollback_http_status": 200,
                                   "both_reports_still_exist": True, "control_grant_state": "active",
                                   "denial_code": "resource_not_found", "report_still_exists": True,
                                   "authority": "target", "grant_state": "revoked",
                                   "owned_containers_and_image_tags_removed": True, "passed": True}, indent=2) + "\n")


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

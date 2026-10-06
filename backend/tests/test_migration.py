"""Deterministic reconciliation, reviewer isolation and cutover gates."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import migration

pytestmark = [pytest.mark.integration, pytest.mark.migration]


def snapshot(ids, settings, issues=None, baseline=True, resource="audience-atlas"):
    return {
        "format": "scopegate-synthetic-v1",
        "records": [
            {
                "source_kind": "grant",
                "source_key": "grant-001",
                "organization_id": ids["organizations"]["cedar"],
                "issuer": settings.oidc_issuer,
                "subject": "viewer-cedar",
                "baseline_allowed": baseline,
                "project_id": ids["projects"]["harbor"],
                "resource_id": ids["resources"][resource],
                "issues": issues or [],
                "source_sequence": 1,
            }
        ],
    }


def baseline(ids, settings, allowed=True, resource="market-pulse"):
    return {
        "format": "scopegate-decisions-v1",
        "decisions": [
            {
                "principal_key": settings.oidc_issuer + "|viewer-cedar",
                "project_key": ids["projects"]["harbor"],
                "resource_key": resource,
                "action": "consume",
                "allowed": allowed,
            },
            {
                "principal_key": settings.oidc_issuer + "|guest-invite",
                "project_key": ids["projects"]["harbor"],
                "resource_key": resource,
                "action": "consume",
                "allowed": False,
            },
        ],
    }


def test_profile_accounts_for_every_element_and_replay_is_idempotent(seed, ids, settings):
    data = snapshot(ids, settings, issues=["Conflicting embedded access fields"])
    data["records"] += [
        {
            "source_kind": "report_ref",
            "source_key": "report-001",
            "organization_id": ids["organizations"]["cedar"],
            "issues": ["Unknown report resource"],
        },
        {
            "source_kind": "localization",
            "source_key": "locale-001",
            "organization_id": ids["organizations"]["cedar"],
            "issues": ["Duplicate locale rows"],
        },
        {
            "source_kind": "retained",
            "source_key": "isolated-001",
            "organization_id": ids["organizations"]["cedar"],
        },
    ]
    first = migration.backfill(data)
    second = migration.backfill(data)
    assert first["run_id"] == second["run_id"] and first["source_elements"] == 4
    with db.transaction() as conn:
        items = db.rows(conn, "SELECT * FROM migration_ledger WHERE run_id=:run", {"run": first["run_id"]})
    assert len(items) == 4 and sum(item["outcome"] == "review_required" for item in items) == 3


def test_unverified_identity_and_unknown_baseline_remain_unresolved(seed, ids, settings):
    data = snapshot(ids, settings, baseline=None)
    del data["records"][0]["subject"]
    result = migration.backfill(data)
    with db.transaction() as conn:
        item = db.row(conn, "SELECT * FROM migration_ledger WHERE run_id=:id", {"id": result["run_id"]})
    assert item["outcome"] == "review_required" and "identity" in item["decision_reason"]


def test_exact_backfill_creates_only_reviewed_grant_once(seed, ids, settings, admin_engine):
    org = ids["organizations"]["cedar"]
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE organizations SET access_mode='legacy' WHERE id=:id"), {"id": org})
    data = snapshot(ids, settings)
    first = migration.backfill(data)
    second = migration.backfill(data)
    assert first["grants_added"] == 1 and second["grants_added"] == 0
    with db.transaction() as conn:
        count = db.row(
            conn,
            "SELECT count(*) AS count FROM resource_grants WHERE organization_id=:org AND membership_id=:member AND resource_id=:resource",
            {
                "org": org,
                "member": ids["memberships"]["viewer"],
                "resource": ids["resources"]["audience-atlas"],
            },
        )["count"]
    assert count == 1


def test_backfill_cannot_mutate_target_authority(seed, ids, settings):
    result = migration.backfill(snapshot(ids, settings))
    assert result["grants_added"] == 0
    with db.transaction() as conn:
        item = db.row(
            conn, "SELECT outcome FROM migration_ledger WHERE run_id=:run", {"run": result["run_id"]}
        )
    assert item["outcome"] == "review_required"


def test_unknown_resource_becomes_review_without_partial_grant(seed, ids, settings, admin_engine):
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE organizations SET access_mode='legacy' WHERE id=:id"),
            {"id": ids["organizations"]["cedar"]},
        )
    data = snapshot(ids, settings)
    data["records"][0]["resource_id"] = str(uuid4())
    result = migration.backfill(data)
    with db.transaction() as conn:
        item = db.row(
            conn, "SELECT outcome FROM migration_ledger WHERE run_id=:run", {"run": result["run_id"]}
        )
    assert item["outcome"] == "review_required"


def test_customer_cannot_review_and_cross_tenant_workbench_is_concealed(manager, reviewer, ids):
    org = ids["organizations"]["cedar"]
    with pytest.raises(AppError) as error:
        migration.list_runs(manager, org)
    assert error.value.status == 403
    runs = migration.list_runs(reviewer, org)
    assert runs["items"][0]["unresolved_count"] == 2
    with pytest.raises(AppError) as error:
        migration.list_items(reviewer, ids["organizations"]["birch"], runs["items"][0]["id"])
    assert error.value.status == 404


def test_expired_reviewer_is_denied(reviewer, ids, admin_engine):
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE memberships SET created_at=clock_timestamp()-interval '2 days',expires_at=clock_timestamp()-interval '1 day' WHERE id=:id"
            ),
            {"id": ids["memberships"]["operator"]},
        )
    with pytest.raises(AppError) as error:
        migration.list_runs(reviewer, ids["organizations"]["cedar"])
    assert error.value.status == 403


def test_review_is_versioned_idempotent_and_does_not_grant(reviewer, ids):
    org = ids["organizations"]["cedar"]
    run = migration.list_runs(reviewer, org)["items"][0]
    entry = migration.list_items(reviewer, org, run["id"])["items"][0]
    body = {
        "outcome": "rejected",
        "decision_reason": "Reviewed source does not establish an exact entitlement.",
    }
    key = str(uuid4())
    result = migration.resolve(reviewer, org, run["id"], entry["id"], body, entry["review_version"], key)
    assert result["review_version"] == entry["review_version"] + 1
    assert (
        migration.resolve(reviewer, org, run["id"], entry["id"], body, entry["review_version"], key) == result
    )
    with pytest.raises(AppError) as error:
        migration.resolve(reviewer, org, run["id"], entry["id"], body, entry["review_version"], str(uuid4()))
    assert error.value.status == 412
    with db.transaction() as conn:
        assert (
            db.row(conn, "SELECT access_mode FROM organizations WHERE id=:org", {"org": org})["access_mode"]
            == "target"
        )


def test_gain_and_unknown_decisions_block_cutover(seed, ids, settings):
    data = snapshot(ids, settings, issues=["Requires owner review"])
    run = migration.profile(data)
    org = ids["organizations"]["cedar"]
    compared = migration.compare(run["run_id"], org, baseline(ids, settings, allowed=False))
    assert compared["gains"] == 1 and not compared["cutover_ready"]
    fence = migration.fence(org, run["run_id"], 1, "reviewed-v1", 0, 0, True)
    with pytest.raises(AppError) as error:
        migration.cutover(
            org,
            run["run_id"],
            fence["writer_epoch"],
            compared["baseline_manifest_hash"],
            compared["target_manifest_hash"],
        )
    assert error.value.code == "cutover_blocked"
    with db.transaction() as conn:
        assert db.row(
            conn, "SELECT write_fenced FROM migration_controls WHERE organization_id=:org", {"org": org}
        )["write_fenced"]


def test_unscoped_writer_and_stale_epoch_are_rejected(seed, ids, settings):
    run = migration.profile(snapshot(ids, settings, issues=["Requires review"]))
    org = ids["organizations"]["cedar"]
    with pytest.raises(AppError) as error:
        migration.fence(org, run["run_id"], 1, "v1", 0, 0, False)
    assert error.value.code == "unscoped_writer_active"
    migration.fence(org, run["run_id"], 1, "v1", 0, 0, True)
    with pytest.raises(AppError) as error:
        migration.fence(org, run["run_id"], 1, "v1", 0, 0, True)
    assert error.value.status == 412


def test_unapplied_high_watermark_keeps_tenant_fenced(seed, ids, settings):
    run = migration.profile(snapshot(ids, settings, resource="market-pulse"))
    org = ids["organizations"]["cedar"]
    compared = migration.compare(run["run_id"], org, baseline(ids, settings))
    fence = migration.fence(org, run["run_id"], 1, "v1", 2, 1, True)
    with pytest.raises(AppError) as error:
        migration.cutover(
            org,
            run["run_id"],
            fence["writer_epoch"],
            compared["baseline_manifest_hash"],
            compared["target_manifest_hash"],
        )
    assert error.value.code == "deltas_unapplied"


def test_cutover_requires_current_parity_then_preserves_target_ownership(seed, ids, settings, admin_engine):
    org = ids["organizations"]["cedar"]
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE organizations SET access_mode='shadow' WHERE id=:id"), {"id": org})
    run = migration.profile(snapshot(ids, settings, resource="market-pulse"))
    compared = migration.compare(run["run_id"], org, baseline(ids, settings))
    assert compared["cutover_ready"]
    fence = migration.fence(org, run["run_id"], 1, "v1", 1, 1, True)
    result = migration.cutover(
        org,
        run["run_id"],
        fence["writer_epoch"],
        compared["baseline_manifest_hash"],
        compared["target_manifest_hash"],
    )
    assert result["access_mode"] == "target" and result["writer_epoch"] == 3
    assert migration.contract_check(org, run["run_id"])["destructive_cleanup_performed"] is False


def test_changed_permissions_after_compare_require_new_manifest(seed, ids, settings, admin_engine):
    org = ids["organizations"]["cedar"]
    run = migration.profile(snapshot(ids, settings, resource="market-pulse"))
    compared = migration.compare(run["run_id"], org, baseline(ids, settings))
    fence = migration.fence(org, run["run_id"], 1, "v1", 1, 1, True)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE resource_grants SET state='revoked' WHERE membership_id=:member AND resource_id=:resource"
            ),
            {"member": ids["memberships"]["viewer"], "resource": ids["resources"]["market-pulse"]},
        )
    with pytest.raises(AppError) as error:
        migration.cutover(
            org,
            run["run_id"],
            fence["writer_epoch"],
            compared["baseline_manifest_hash"],
            compared["target_manifest_hash"],
        )
    assert error.value.status == 412


@pytest.mark.parametrize(
    "value,fragment", [("[invalid", "Malformed"), (None, "Null"), ({"resource": "missing"}, "explicit array")]
)
def test_profiler_detects_malformed_embedded_values_without_annotations(value, fragment):
    issues = migration._source_issues({"source_kind": "report_ref", "embedded_resources": value})
    assert any(fragment in issue for issue in issues)


def test_profiler_detects_duplicate_locale_identity_without_annotations():
    records = [
        {
            "source_kind": "localization",
            "source_key": "one",
            "resource_id": "stable-resource",
            "locale": "pt",
        },
        {
            "source_kind": "localization",
            "source_key": "two",
            "resource_id": "stable-resource",
            "locale": "pt",
        },
        {
            "source_kind": "localization",
            "source_key": "three",
            "resource_id": "stable-resource",
            "locale": "en",
        },
    ]
    assert migration._conflicting_locales(records) == {"one", "two"}

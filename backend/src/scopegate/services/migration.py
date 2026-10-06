"""Synthetic source reconciliation, reviewer workbench and fenced authority changes."""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services.common import (
    audit,
    check_version,
    cursor_uuid,
    decode_cursor,
    encode_cursor,
    page,
    receipt,
    request_hash,
    require_member,
    save_receipt,
    select_fields,
    serialize,
)
from scopegate.services.invariants import required_row

LEDGER_FIELDS = (
    "id",
    "run_id",
    "organization_id",
    "source_kind",
    "source_key",
    "outcome",
    "target_kind",
    "target_id",
    "decision_reason",
    "review_version",
    "assigned_owner_user_id",
)
POLICY_VERSION = "scopegate-policy-v1"
TRANSFORM_VERSION = "scopegate-transform-v2"


def require_reviewer(conn, actor: dict, organization_id: str) -> dict:
    member = require_member(conn, actor, organization_id, manager=True)
    if member["kind"] != "staff" or not member["can_review_migration"]:
        raise AppError(
            403, "migration_review_required", "An explicitly assigned migration reviewer is required."
        )
    return member


def _run(conn, organization_id: str, run_id: str) -> dict:
    run = db.row(
        conn,
        """
        SELECT r.* FROM migration_runs r WHERE r.id=:id AND EXISTS(
          SELECT 1 FROM migration_ledger l WHERE l.run_id=r.id AND l.organization_id=:org)
    """,
        {"id": str(run_id), "org": str(organization_id)},
    )
    if not run:
        raise AppError(404, "migration_run_not_found", "Migration run was not found.")
    return run


def run_view(conn, organization_id: str, run: dict) -> dict:
    unresolved = required_row(
        conn,
        "SELECT count(*) AS count FROM migration_ledger WHERE run_id=:run AND organization_id=:org AND outcome='review_required'",
        {"run": str(run["id"]), "org": str(organization_id)},
    )["count"]
    counts = required_row(
        conn,
        """
        SELECT count(*) FILTER(WHERE baseline_allowed=false AND target_allowed=true) AS gains,
               count(*) FILTER(WHERE baseline_allowed=true AND target_allowed=false) AS losses
        FROM migration_decisions WHERE run_id=:run AND organization_id=:org
    """,
        {"run": str(run["id"]), "org": str(organization_id)},
    )
    return serialize(
        {
            "id": run["id"],
            "state": run["state"],
            "snapshot_hash": run["snapshot_hash"],
            "baseline_manifest_hash": run["baseline_manifest_hash"],
            "target_manifest_hash": run["target_manifest_hash"],
            "unresolved_count": unresolved,
            "unreviewed_gain_count": counts["gains"],
            "unreviewed_loss_count": counts["losses"],
        }
    )


def list_runs(actor: dict, organization_id: str, limit: int = 25, cursor: str | None = None) -> dict:
    scope = ["migration-runs", str(organization_id), actor["user_id"]]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        require_reviewer(conn, actor, organization_id)
        runs = db.rows(
            conn,
            """
            SELECT r.* FROM migration_runs r WHERE EXISTS(
              SELECT 1 FROM migration_ledger l WHERE l.run_id=r.id AND l.organization_id=:org)
              AND (CAST(:marker AS uuid) IS NULL OR r.id>CAST(:marker AS uuid)) ORDER BY r.id LIMIT :limit
        """,
            {"org": str(organization_id), "marker": marker, "limit": limit + 1},
        )
        items = [run_view(conn, organization_id, run) for run in runs]
    return page(items, limit, scope, cursor)


def list_items(
    actor: dict, organization_id: str, run_id: str, limit: int = 25, cursor: str | None = None
) -> dict:
    scope = ["migration-items", str(organization_id), str(run_id), actor["user_id"]]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        require_reviewer(conn, actor, organization_id)
        _run(conn, organization_id, run_id)
        items = db.rows(
            conn,
            """
            SELECT * FROM migration_ledger WHERE run_id=:run AND organization_id=:org
              AND (CAST(:marker AS uuid) IS NULL OR id>CAST(:marker AS uuid)) ORDER BY id LIMIT :limit
        """,
            {"org": str(organization_id), "run": str(run_id), "marker": marker, "limit": limit + 1},
        )
    return page([select_fields(item, LEDGER_FIELDS) for item in items], limit, scope, cursor)


def resolve(
    actor: dict, organization_id: str, run_id: str, ledger_id: str, body: dict, expected: int, key: str
) -> dict:
    payload = {
        "run_id": str(run_id),
        "ledger_id": str(ledger_id),
        "expected_version": expected,
        **serialize(body),
    }
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        require_reviewer(conn, actor, organization_id)
        run = _run(conn, organization_id, run_id)
        if run["state"] in {"cutover", "aborted"}:
            raise AppError(409, "migration_closed", "A closed migration run cannot be reviewed.")
        stored = receipt(conn, actor, organization_id, "migration.resolve", key, payload)
        if stored:
            return stored
        entry = db.row(
            conn,
            "SELECT * FROM migration_ledger WHERE organization_id=:org AND run_id=:run AND id=:id FOR UPDATE",
            {"org": str(organization_id), "run": str(run_id), "id": str(ledger_id)},
        )
        if not entry:
            raise AppError(404, "ledger_not_found", "Reconciliation item was not found.")
        check_version(entry["review_version"], expected, "review_version_conflict")
        owner = body.get("assigned_owner_user_id")
        if owner and not db.row(conn, "SELECT id FROM users WHERE id=:id", {"id": str(owner)}):
            raise AppError(
                422, "validation_error", "The assigned owner must be an existing verified identity."
            )
        entry = required_row(
            conn,
            """
            UPDATE migration_ledger SET outcome=:outcome,target_kind=:kind,target_id=:target,
              decision_reason=:reason,assigned_owner_user_id=:owner,reviewed_by=:reviewer,
              reviewed_at=clock_timestamp(),review_version=review_version+1
            WHERE id=:id RETURNING *
        """,
            {
                "id": str(ledger_id),
                "outcome": body["outcome"],
                "kind": body.get("target_kind"),
                "target": body.get("target_id"),
                "reason": body["decision_reason"].strip(),
                "owner": str(owner) if owner else None,
                "reviewer": actor["user_id"],
            },
        )
        conn.execute(
            text(
                "UPDATE migration_runs SET baseline_manifest_hash=NULL,target_manifest_hash=NULL,state='backfilled' WHERE id=:id"
            ),
            {"id": str(run_id)},
        )
        audit(
            conn,
            actor,
            organization_id,
            "migration.item_reviewed",
            "migration_ledger",
            ledger_id,
            {
                "outcome": body["outcome"],
                "reason": body["decision_reason"],
                "review_version": entry["review_version"],
            },
        )
        response = select_fields(entry, LEDGER_FIELDS)
        save_receipt(conn, actor, organization_id, "migration.resolve", key, payload, response)
        return response


def export_manifest(
    actor: dict, organization_id: str, run_id: str, limit: int = 25, cursor: str | None = None
) -> dict:
    scope = ["migration-manifest", str(organization_id), str(run_id), actor["user_id"]]
    with db.transaction() as conn:
        require_reviewer(conn, actor, organization_id)
        run = _run(conn, organization_id, run_id)
        revision = [run["baseline_manifest_hash"], run["target_manifest_hash"]]
        marker = decode_cursor(cursor, scope, revision)
        if marker is not None and (not isinstance(marker, list) or len(marker) != 4):
            raise AppError(422, "validation_error", "The manifest cursor is malformed.")
        keys = marker or ["", "", "", ""]
        decisions = db.rows(
            conn,
            """
            SELECT principal_key,project_key,resource_key,action,baseline_allowed,target_allowed,reason
            FROM migration_decisions WHERE run_id=:run AND organization_id=:org
              AND (principal_key,project_key,resource_key,action)>(:principal,:project,:resource,:action)
            ORDER BY principal_key,project_key,resource_key,action LIMIT :limit
        """,
            {
                "org": str(organization_id),
                "run": str(run_id),
                "principal": keys[0],
                "project": keys[1],
                "resource": keys[2],
                "action": keys[3],
                "limit": limit + 1,
            },
        )
    visible = decisions[:limit]
    next_cursor = None
    if len(decisions) > limit:
        last = visible[-1]
        next_cursor = encode_cursor(
            scope, [last[k] for k in ["principal_key", "project_key", "resource_key", "action"]], revision
        )
    return {"items": serialize(visible), "next_cursor": next_cursor}


def validate_snapshot(snapshot: dict) -> list[dict]:
    if snapshot.get("format") != "scopegate-synthetic-v1" or not isinstance(snapshot.get("records"), list):
        raise AppError(422, "snapshot_invalid", "Use an explicit scopegate-synthetic-v1 snapshot.")
    records = snapshot["records"]
    if not 1 <= len(records) <= 1000:
        raise AppError(422, "snapshot_invalid", "The local fixture must contain 1 to 1000 source elements.")
    keys = set()
    for record in records:
        if not isinstance(record, dict) or not record.get("source_kind") or not record.get("source_key"):
            raise AppError(422, "snapshot_invalid", "Every source element requires kind and stable key.")
        key = (record["source_kind"], record["source_key"])
        if key in keys:
            raise AppError(422, "snapshot_invalid", "Source keys must be unique within their kind.")
        keys.add(key)
    return records


def profile(snapshot: dict, evidence_revision: str = "local-synthetic") -> dict:
    records = validate_snapshot(snapshot)
    digest = request_hash(snapshot)
    run_id = str(uuid5(NAMESPACE_URL, "scopegate:migration:" + digest + ":" + TRANSFORM_VERSION))
    conflicts = _conflicting_locales(records)
    with db.transaction() as conn:
        conn.execute(
            text("""
            INSERT INTO migration_runs(id,snapshot_hash,policy_version,evidence_revision,state)
            VALUES(:id,:hash,:policy,:revision,'profiled') ON CONFLICT(id) DO NOTHING
        """),
            {"id": run_id, "hash": digest, "policy": POLICY_VERSION, "revision": evidence_revision},
        )
        for record in records:
            detected = (
                ["Duplicate stable resource and locale mapping."]
                if record["source_kind"] == "localization" and record["source_key"] in conflicts
                else []
            )
            _profile_record(conn, run_id, record, detected)
    return {"run_id": run_id, "snapshot_hash": digest, "source_elements": len(records)}


def _embedded_issues(record: dict) -> list[str]:
    if "embedded_resources" not in record:
        return []
    value = record["embedded_resources"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return ["Malformed embedded resource association."]
    if value is None:
        return ["Null embedded resource association requires explicit disposition."]
    if not isinstance(value, list):
        return ["Embedded resource association must be an explicit array."]
    return []


def _conflicting_locales(records: list[dict]) -> set[str]:
    seen: dict[tuple, str] = {}
    conflicts: set[str] = set()
    for record in records:
        if record["source_kind"] != "localization":
            continue
        identity = (record.get("resource_id"), record.get("locale"))
        if not all(identity):
            continue
        if identity in seen:
            conflicts.update([record["source_key"], seen[identity]])
        seen[identity] = record["source_key"]
    return conflicts


def _source_issues(record: dict) -> list[str]:
    issues = list(record.get("issues", [])) + _embedded_issues(record)
    if record.get("source_kind") == "grant":
        if record.get("baseline_allowed") is None:
            issues.append("effective baseline unavailable")
        if not record.get("issuer") or not record.get("subject"):
            issues.append("verified identity mapping unavailable")
    return issues


def _profile_record(conn, run_id: str, record: dict, detected_issues: list[str] | None = None) -> None:
    org = record.get("organization_id")
    if org:
        try:
            org = str(UUID(org))
        except (ValueError, TypeError) as exc:
            raise AppError(
                422, "snapshot_invalid", "Organization references must be explicit UUIDs."
            ) from exc
        if not db.row(conn, "SELECT id FROM organizations WHERE id=:id", {"id": org}):
            raise AppError(
                422, "snapshot_invalid", "Organization mappings must be established before profiling."
            )
    issues = _source_issues(record) + (detected_issues or [])
    outcome = "review_required" if issues else "retained" if record["source_kind"] == "retained" else "mapped"
    identifier = str(
        uuid5(NAMESPACE_URL, f"scopegate:ledger:{run_id}:{record['source_kind']}:{record['source_key']}")
    )
    conn.execute(
        text("""
        INSERT INTO migration_ledger(id,run_id,organization_id,source_kind,source_key,source_hash,
          transform_version,source_sequence,outcome,target_kind,target_id,decision_reason)
        VALUES(:id,:run,:org,:kind,:key,:hash,:version,:sequence,:outcome,:target_kind,:target,:reason)
        ON CONFLICT(run_id,source_kind,source_key) DO NOTHING
    """),
        {
            "id": identifier,
            "run": run_id,
            "org": org,
            "kind": record["source_kind"],
            "key": record["source_key"],
            "hash": request_hash(record),
            "version": TRANSFORM_VERSION,
            "sequence": record.get("source_sequence", 0),
            "outcome": outcome,
            "target_kind": record.get("target_kind"),
            "target": record.get("target_id"),
            "reason": "; ".join(issues) if issues else "Exact synthetic source mapping recorded.",
        },
    )


def backfill(snapshot: dict) -> dict:
    result = profile(snapshot)
    run_id = result["run_id"]
    totals = {"mapped": 0, "review_required": 0, "retained": 0, "grants_added": 0}
    for record in validate_snapshot(snapshot):
        with db.transaction() as conn:
            entry = required_row(
                conn,
                "SELECT * FROM migration_ledger WHERE run_id=:run AND source_kind=:kind AND source_key=:key FOR UPDATE",
                {"run": run_id, "kind": record["source_kind"], "key": record["source_key"]},
            )
            outcome = entry["outcome"]
            totals[outcome if outcome in totals else "mapped"] += 1
            if record["source_kind"] == "grant" and outcome == "mapped":
                totals["grants_added"] += _backfill_grant(conn, record, entry)
    with db.transaction() as conn:
        conn.execute(
            text("UPDATE migration_runs SET state='backfilled' WHERE id=:id AND state='profiled'"),
            {"id": run_id},
        )
    return {**result, **totals}


def _grant_identifiers(conn, record: dict, entry: dict) -> tuple[str, str] | None:
    try:
        resource = str(UUID(record.get("resource_id", "")))
        project = str(UUID(record.get("project_id", "")))
    except (ValueError, TypeError, AttributeError):
        _mark_review(conn, entry["id"], "Exact project and resource mapping unavailable or malformed.")
        return None
    if not db.row(conn, "SELECT id FROM resources WHERE id=:id", {"id": resource}):
        _mark_review(conn, entry["id"], "Referenced resource does not exist in the approved catalog mapping.")
        return None
    return project, resource


def _grant_member(conn, record: dict, org: str, project: str, resource: str) -> dict | None:
    user = db.row(
        conn,
        "SELECT id FROM users WHERE issuer=:issuer AND subject=:subject",
        {"issuer": record["issuer"], "subject": record["subject"]},
    )
    if not user:
        return None
    member = db.row(
        conn,
        "SELECT * FROM memberships WHERE organization_id=:org AND user_id=:user FOR UPDATE",
        {"org": org, "user": str(user["id"])},
    )
    entitlement = db.row(
        conn,
        """
        SELECT pr.status,p.status AS project_status,r.status AS resource_status FROM project_resources pr
        JOIN projects p ON p.id=pr.project_id JOIN resources r ON r.id=pr.resource_id
        WHERE pr.organization_id=:org AND pr.project_id=:project AND pr.resource_id=:resource
    """,
        {"org": org, "project": project, "resource": resource},
    )
    if not member or not entitlement:
        return None
    states = [
        member["status"],
        entitlement["status"],
        entitlement["project_status"],
        entitlement["resource_status"],
    ]
    if states != ["active", "active", "active", "published"]:
        return None
    if member["expires_at"] is not None and member["expires_at"] <= db.clock(conn):
        return None
    return member


def _backfill_grant(conn, record: dict, entry: dict) -> int:
    org = str(entry["organization_id"])
    identifiers = _grant_identifiers(conn, record, entry)
    if identifiers is None:
        return 0
    project, resource = identifiers
    db.lock_resources(conn, [resource])
    organization = db.lock_org(conn, org)
    if organization["access_mode"] == "target":
        _mark_review(
            conn, entry["id"], "Backfill cannot mutate an organization already owned by target writers."
        )
        return 0
    member = _grant_member(conn, record, org, project, resource)
    if member is None:
        _mark_review(conn, entry["id"], "Exact verified member and active entitlement mapping unavailable.")
        return 0
    if record["baseline_allowed"] is not True:
        return 0
    result = conn.execute(
        text("""
        INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id,state)
        VALUES(:org,:member,:project,:resource,'active') ON CONFLICT DO NOTHING
    """),
        {"org": org, "member": str(member["id"]), "project": project, "resource": resource},
    )
    if result.rowcount:
        conn.execute(
            text("UPDATE memberships SET access_version=access_version+1 WHERE id=:id"),
            {"id": str(member["id"])},
        )
    return result.rowcount


def _mark_review(conn, ledger_id, reason: str) -> None:
    conn.execute(
        text("UPDATE migration_ledger SET outcome='review_required',decision_reason=:reason WHERE id=:id"),
        {"id": str(ledger_id), "reason": reason},
    )


def compare(run_id: str, organization_id: str, baseline: dict) -> dict:
    if baseline.get("format") != "scopegate-decisions-v1" or not isinstance(baseline.get("decisions"), list):
        raise AppError(422, "baseline_invalid", "An explicit reviewed allow and deny manifest is required.")
    decisions = baseline["decisions"]
    if not 1 <= len(decisions) <= 1000:
        raise AppError(422, "baseline_invalid", "The local decision manifest must contain 1 to 1000 tuples.")
    gains = losses = unknown = 0
    target = []
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        run = _run(conn, organization_id, run_id)
        if run["state"] in {"cutover", "aborted"}:
            raise AppError(409, "migration_closed", "The migration run is closed.")
        conn.execute(
            text("DELETE FROM migration_decisions WHERE run_id=:run AND organization_id=:org"),
            {"run": str(run_id), "org": str(organization_id)},
        )
        for decision in decisions:
            allowed = _target_decision(conn, organization_id, decision)
            baseline_allowed = decision.get("allowed")
            if not isinstance(baseline_allowed, bool):
                unknown += 1
                baseline_allowed = None
            gains += baseline_allowed is False and allowed
            losses += baseline_allowed is True and not allowed
            item = {
                "principal_key": decision["principal_key"],
                "project_key": decision["project_key"],
                "resource_key": decision["resource_key"],
                "action": decision.get("action", "consume"),
                "baseline_allowed": baseline_allowed,
                "target_allowed": allowed,
                "reason": "Parity verified."
                if baseline_allowed == allowed
                else "Unknown or divergent decision requires review.",
            }
            target.append(item)
            conn.execute(
                text("""
                INSERT INTO migration_decisions(run_id,organization_id,principal_key,project_key,resource_key,
                  action,baseline_allowed,target_allowed,reason)
                VALUES(:run,:org,:principal_key,:project_key,:resource_key,:action,:baseline_allowed,:target_allowed,:reason)
            """),
                {"run": str(run_id), "org": str(organization_id), **item},
            )
        baseline_hash = request_hash(baseline)
        target_hash = request_hash(
            sorted(
                target,
                key=lambda item: (
                    item["principal_key"],
                    item["project_key"],
                    item["resource_key"],
                    item["action"],
                ),
            )
        )
        conn.execute(
            text(
                "UPDATE migration_runs SET baseline_manifest_hash=:baseline,target_manifest_hash=:target,state='shadow' WHERE id=:run"
            ),
            {"run": str(run_id), "baseline": baseline_hash, "target": target_hash},
        )
        unresolved = required_row(
            conn,
            "SELECT count(*) AS count FROM migration_ledger WHERE run_id=:run AND organization_id=:org AND outcome='review_required'",
            {"run": str(run_id), "org": str(organization_id)},
        )["count"]
    return {
        "run_id": str(run_id),
        "organization_id": str(organization_id),
        "baseline_manifest_hash": baseline_hash,
        "target_manifest_hash": target_hash,
        "gains": gains,
        "losses": losses,
        "unknown": unknown,
        "unresolved": unresolved,
        "cutover_ready": not any([gains, losses, unknown, unresolved]),
    }


def _target_decision(conn, organization_id: str, decision: dict) -> bool:
    if decision.get("action", "consume") != "consume":
        return False
    identity = decision["principal_key"].rsplit("|", 1)
    if len(identity) != 2:
        return False
    return bool(
        db.row(
            conn,
            """
        SELECT 1 FROM organizations o JOIN memberships m ON m.organization_id=o.id
        JOIN users u ON u.id=m.user_id JOIN projects p ON p.organization_id=o.id
        JOIN project_resources pr ON pr.organization_id=o.id AND pr.project_id=p.id
        JOIN resources r ON r.id=pr.resource_id JOIN resource_grants g ON g.organization_id=o.id
          AND g.membership_id=m.id AND g.project_id=p.id AND g.resource_id=r.id
        WHERE o.id=:org AND o.status='active' AND m.status='active'
          AND (m.expires_at IS NULL OR m.expires_at>clock_timestamp())
          AND p.status='active' AND pr.status='active' AND r.status='published' AND g.state='active'
          AND u.issuer=:issuer AND u.subject=:subject AND p.id=CAST(:project AS uuid) AND r.external_key=:resource
    """,
            {
                "org": str(organization_id),
                "issuer": identity[0],
                "subject": identity[1],
                "project": str(UUID(decision["project_key"])),
                "resource": decision["resource_key"],
            },
        )
    )


def fence(
    organization_id: str,
    run_id: str,
    expected_epoch: int,
    baseline_revision: str,
    source_high_watermark: int,
    applied_high_watermark: int,
    unscoped_writer_disabled: bool,
) -> dict:
    if not unscoped_writer_disabled:
        raise AppError(
            409, "unscoped_writer_active", "The unscoped writer must be disabled before a tenant fence."
        )
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        _run(conn, organization_id, run_id)
        control = db.row(
            conn,
            "SELECT * FROM migration_controls WHERE organization_id=:org FOR UPDATE",
            {"org": str(organization_id)},
        )
        epoch = control["writer_epoch"] if control else 1
        check_version(epoch, expected_epoch, "writer_epoch_conflict")
        conn.execute(
            text("""
            INSERT INTO migration_controls(organization_id,writer_epoch,write_fenced,source_high_watermark,
              applied_high_watermark,baseline_revision,current_run_id)
            VALUES(:org,:epoch,true,:source,:applied,:revision,:run)
            ON CONFLICT(organization_id) DO UPDATE SET writer_epoch=EXCLUDED.writer_epoch,write_fenced=true,
              source_high_watermark=EXCLUDED.source_high_watermark,applied_high_watermark=EXCLUDED.applied_high_watermark,
              baseline_revision=EXCLUDED.baseline_revision,current_run_id=EXCLUDED.current_run_id,updated_at=clock_timestamp()
        """),
            {
                "org": str(organization_id),
                "epoch": epoch + 1,
                "source": source_high_watermark,
                "applied": applied_high_watermark,
                "revision": baseline_revision,
                "run": str(run_id),
            },
        )
        audit(
            conn,
            {"actor_key": "service:migration"},
            organization_id,
            "migration.fenced",
            "organization",
            organization_id,
            {"writer_epoch": epoch + 1},
        )
    return {"organization_id": str(organization_id), "writer_epoch": epoch + 1, "write_fenced": True}


def cutover(
    organization_id: str,
    run_id: str,
    expected_epoch: int,
    expected_baseline_hash: str,
    expected_target_hash: str,
) -> dict:
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        run = _run(conn, organization_id, run_id)
        control = db.row(
            conn,
            "SELECT * FROM migration_controls WHERE organization_id=:org FOR UPDATE",
            {"org": str(organization_id)},
        )
        if not control or not control["write_fenced"] or str(control["current_run_id"]) != str(run_id):
            raise AppError(409, "fence_required", "A current reviewed writer fence is required.")
        check_version(control["writer_epoch"], expected_epoch, "writer_epoch_conflict")
        if control["source_high_watermark"] != control["applied_high_watermark"]:
            raise AppError(
                409, "deltas_unapplied", "Source deltas remain unapplied; keep the organization fenced."
            )
        if (
            run["baseline_manifest_hash"] != expected_baseline_hash
            or run["target_manifest_hash"] != expected_target_hash
        ):
            raise AppError(412, "manifest_changed", "The reviewed comparison manifest changed.")
        _cutover_gates(conn, organization_id, run_id)
        conn.execute(
            text("UPDATE organizations SET access_mode='target' WHERE id=:org"), {"org": str(organization_id)}
        )
        conn.execute(
            text(
                "UPDATE migration_controls SET writer_epoch=writer_epoch+1,write_fenced=false,updated_at=clock_timestamp() WHERE organization_id=:org"
            ),
            {"org": str(organization_id)},
        )
        conn.execute(text("UPDATE migration_runs SET state='cutover' WHERE id=:run"), {"run": str(run_id)})
        audit(
            conn,
            {"actor_key": "service:migration"},
            organization_id,
            "migration.cutover",
            "organization",
            organization_id,
            {"writer_epoch": expected_epoch + 1},
        )
    return {
        "organization_id": str(organization_id),
        "access_mode": "target",
        "writer_epoch": expected_epoch + 1,
    }


def _cutover_gates(conn, organization_id: str, run_id: str) -> None:
    unresolved = required_row(
        conn,
        "SELECT count(*) AS count FROM migration_ledger WHERE run_id=:run AND (organization_id=:org OR organization_id IS NULL) AND outcome='review_required'",
        {"run": str(run_id), "org": str(organization_id)},
    )["count"]
    decisions = db.rows(
        conn,
        "SELECT * FROM migration_decisions WHERE run_id=:run AND organization_id=:org",
        {"run": str(run_id), "org": str(organization_id)},
    )
    if (
        unresolved
        or not decisions
        or any(
            item["baseline_allowed"] is None
            or item["target_allowed"] is None
            or item["baseline_allowed"] != item["target_allowed"]
            for item in decisions
        )
    ):
        raise AppError(
            409, "cutover_blocked", "Unresolved source elements or divergent decisions block cutover."
        )
    for item in decisions:
        if _target_decision(conn, organization_id, item) != item["target_allowed"]:
            raise AppError(
                412, "manifest_changed", "Current permissions no longer match the reviewed target manifest."
            )
    durable = db.row(
        conn,
        "SELECT id FROM memberships WHERE organization_id=:org AND role='access_manager' AND kind='customer' AND status='active' AND expires_at IS NULL LIMIT 1",
        {"org": str(organization_id)},
    )
    if not durable:
        raise AppError(409, "manager_continuity_required", "A durable customer access manager is required.")


def unfence(organization_id: str, expected_epoch: int, reason: str) -> dict:
    if len(reason.strip()) < 8:
        raise AppError(422, "validation_error", "An explicit recovery reason is required.")
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        control = db.row(
            conn,
            "SELECT * FROM migration_controls WHERE organization_id=:org FOR UPDATE",
            {"org": str(organization_id)},
        )
        if not control:
            raise AppError(404, "control_not_found", "Migration control was not found.")
        check_version(control["writer_epoch"], expected_epoch, "writer_epoch_conflict")
        conn.execute(
            text(
                "UPDATE migration_controls SET writer_epoch=writer_epoch+1,write_fenced=false,updated_at=clock_timestamp() WHERE organization_id=:org"
            ),
            {"org": str(organization_id)},
        )
        audit(
            conn,
            {"actor_key": "service:migration"},
            organization_id,
            "migration.unfenced",
            "organization",
            organization_id,
            {"reason": reason, "writer_epoch": expected_epoch + 1},
        )
    return {
        "organization_id": str(organization_id),
        "writer_epoch": expected_epoch + 1,
        "write_fenced": False,
    }


def contract_check(organization_id: str, run_id: str) -> dict:
    with db.transaction() as conn:
        run = _run(conn, organization_id, run_id)
        organization = required_row(
            conn, "SELECT access_mode FROM organizations WHERE id=:id", {"id": str(organization_id)}
        )
        if run["state"] != "cutover" or organization["access_mode"] != "target":
            raise AppError(409, "contract_blocked", "Target ownership and a completed cutover are required.")
        _cutover_gates(conn, organization_id, run_id)
    return {
        "organization_id": str(organization_id),
        "contract_ready": True,
        "destructive_cleanup_performed": False,
    }


def seed_demo_migration(conn, organization_id: str, reviewer_user_id: str | None = None) -> str:
    run_id = str(uuid5(NAMESPACE_URL, "scopegate:demo-migration:v1:" + str(organization_id)))
    conn.execute(
        text("""
        INSERT INTO migration_runs(id,snapshot_hash,policy_version,evidence_revision,state)
        VALUES(:id,:hash,:policy,'local-synthetic','backfilled') ON CONFLICT DO NOTHING
    """),
        {"id": run_id, "hash": hashlib.sha256(b"scopegate-demo-v1").hexdigest(), "policy": POLICY_VERSION},
    )
    examples = [
        (
            "association",
            "grant-review-001",
            "review_required",
            "The two source fields disagree; verify the intended project and resource.",
        ),
        (
            "report_ref",
            "report-ref-001",
            "review_required",
            "A stored report reference points to an unknown resource.",
        ),
        (
            "localization",
            "translation-001",
            "mapped",
            "Stable resource identity and locale mapping verified.",
        ),
        (
            "retained",
            "isolated-record-001",
            "retained",
            "The isolated source record remains outside the access transformation.",
        ),
    ]
    for kind, key, outcome, reason in examples:
        conn.execute(
            text("""
            INSERT INTO migration_ledger(id,run_id,organization_id,source_kind,source_key,source_hash,
              transform_version,outcome,decision_reason,assigned_owner_user_id)
            VALUES(:id,:run,:org,:kind,:key,:hash,:transform,:outcome,:reason,:owner) ON CONFLICT DO NOTHING
        """),
            {
                "id": str(uuid5(NAMESPACE_URL, run_id + key)),
                "run": run_id,
                "org": str(organization_id),
                "kind": kind,
                "key": key,
                "hash": request_hash([kind, key]),
                "transform": TRANSFORM_VERSION,
                "outcome": outcome,
                "reason": reason,
                "owner": str(reviewer_user_id) if reviewer_user_id else None,
            },
        )
    return run_id

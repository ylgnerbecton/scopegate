"""Independent restore fencing and conservative journal reconciliation."""

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from scopegate import db, journal
from scopegate.config import get_settings
from scopegate.errors import AppError
from scopegate.services.common import audit, check_version
from scopegate.services.invariants import required_row


def marker_path(organization_id: str) -> Path:
    return get_settings().journal_directory / "restore-fences" / (str(UUID(str(organization_id))) + ".json")


def assert_open(organization_id: str) -> None:
    try:
        if not get_settings().journal_directory.is_dir():
            raise OSError("Independent journal directory is unavailable")
        fenced = marker_path(organization_id).exists()
    except OSError as exc:
        raise AppError(
            503, "restore_reconciliation_required", "Restore ownership could not be verified."
        ) from exc
    if fenced:
        raise AppError(
            503, "restore_reconciliation_required", "This organization is fenced for restore reconciliation."
        )


def _write_marker(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(journal.canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def begin_restore(organization_id: str, expected_epoch: int) -> dict:
    path = marker_path(organization_id)
    if path.exists():
        return json.loads(path.read_text())
    with db.transaction() as conn:
        organization = db.lock_org(conn, organization_id)
        if organization["access_mode"] != "target":
            raise AppError(
                409, "restore_target_required", "Restore reconciliation requires current target authority."
            )
        control = db.row(
            conn,
            "SELECT * FROM migration_controls WHERE organization_id=:org FOR UPDATE",
            {"org": str(organization_id)},
        )
        epoch = control["writer_epoch"] if control else 1
        check_version(epoch, expected_epoch, "writer_epoch_conflict")
        catalog = _catalog_manifest(conn, organization_id)
        marker = {
            "organization_id": str(organization_id),
            "saved_epoch": epoch,
            "minimum_epoch": epoch + 1,
            "authority": "target",
            "phase": "restore_fenced",
            "catalog_manifest_hash": hashlib.sha256(journal.canonical(catalog)).hexdigest(),
        }
        _write_marker(path, marker)
        conn.execute(
            text("UPDATE organizations SET status='suspended' WHERE id=:org"), {"org": str(organization_id)}
        )
        conn.execute(
            text("""
            INSERT INTO migration_controls(organization_id,writer_epoch,write_fenced,baseline_revision)
            VALUES(:org,:epoch,true,'restore-reconciliation')
            ON CONFLICT(organization_id) DO UPDATE SET writer_epoch=GREATEST(migration_controls.writer_epoch,:epoch),
              write_fenced=true,updated_at=clock_timestamp()
        """),
            {"org": str(organization_id), "epoch": epoch + 1},
        )
    return marker


def _catalog_manifest(conn, organization_id: str) -> list[dict]:
    return db.rows(
        conn,
        "SELECT DISTINCT r.id,r.status,r.catalog_version FROM resources r JOIN project_resources pr ON pr.resource_id=r.id WHERE pr.organization_id=:org ORDER BY r.id",
        {"org": str(organization_id)},
    )


def _journal_outcome(records: list[dict]) -> str:
    phases = [record["phase"] for record in records[1:]]
    if "committed" in phases:
        return "committed"
    if phases and all(phase == "rejected" for phase in phases):
        return "rejected"
    return "uncertain"


def _read_journal_command(path: Path) -> tuple[bytes, dict, str]:
    raw = path.read_bytes()
    if len(raw) > 32000:
        raise AppError(
            409, "restore_scope_exceeded", "A journal command exceeds the bounded local review size."
        )
    try:
        records = [json.loads(line) for line in raw.splitlines()]
        prepared = records[0]
        if prepared["phase"] != "prepared" or prepared["reference"] != path.stem:
            raise ValueError("Invalid prepared journal record")
        status = _journal_outcome(records)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AppError(409, "restore_journal_invalid", "A journal command cannot be verified.") from exc
    return raw, prepared, status


def inspect_journal(organization_id: str) -> dict:
    files = sorted(get_settings().journal_directory.glob("*.jsonl"))
    if len(files) > 128:
        raise AppError(
            409, "restore_scope_exceeded", "Split the restore review into bounded journal manifests."
        )
    commands, digests = [], []
    total_bytes = 0
    for path in files:
        raw, prepared, status = _read_journal_command(path)
        total_bytes += len(raw)
        if total_bytes > 512000:
            raise AppError(409, "restore_scope_exceeded", "The journal review exceeds 512 kilobytes.")
        if prepared.get("organization") != str(organization_id):
            continue
        digests.append({"reference": path.stem, "sha256": hashlib.sha256(raw).hexdigest()})
        commands.append(
            {
                "reference": path.stem,
                "operation": prepared["operation"],
                "delta": prepared["delta"],
                "status": status,
            }
        )
    return {
        "organization_id": str(organization_id),
        "journal_hash": hashlib.sha256(journal.canonical(digests)).hexdigest(),
        "commands": commands,
    }


def _restrict_grants(conn, organization_id: str, delta: dict) -> int:
    member = delta["membership_id"]
    project = delta["project_id"]
    removed = 0
    for resource in delta.get("remove", []):
        result = conn.execute(
            text("""
            UPDATE resource_grants SET state='revoked',updated_at=clock_timestamp()
            WHERE organization_id=:org AND membership_id=:member AND project_id=:project
              AND resource_id=:resource AND state='active'
        """),
            {"org": str(organization_id), "member": member, "project": project, "resource": resource},
        )
        removed += result.rowcount
    conn.execute(
        text("""
        UPDATE memberships SET access_version=GREATEST(access_version,:minimum)
        WHERE organization_id=:org AND id=:member
    """),
        {"org": str(organization_id), "member": member, "minimum": delta.get("expected_version", 1) + 1},
    )
    return removed


def _missing_additions(conn, organization_id: str, delta: dict) -> bool:
    for resource in delta.get("add", []):
        found = db.row(
            conn,
            """
            SELECT 1 FROM resource_grants WHERE organization_id=:org AND membership_id=:member
              AND project_id=:project AND resource_id=:resource AND state='active'
        """,
            {
                "org": str(organization_id),
                "member": delta["membership_id"],
                "project": delta["project_id"],
                "resource": resource,
            },
        )
        if not found:
            return True
    return False


def _apply_restriction(
    conn, organization_id: str, command: dict, confirmed_denials: set[str]
) -> tuple[int, bool]:
    if command["status"] == "rejected":
        return 0, False
    operation, delta = command["operation"], command["delta"]
    confirmed = command["reference"] in confirmed_denials
    unresolved = command["status"] == "uncertain" and not confirmed
    if operation == "grant.diff":
        changed = _restrict_grants(conn, organization_id, delta)
        missing = _missing_additions(conn, organization_id, delta)
        return changed, unresolved or (missing and not confirmed)
    if operation == "membership.status" and delta.get("status") == "suspended":
        result = conn.execute(
            text(
                "UPDATE memberships SET status='suspended',access_version=GREATEST(access_version,:minimum) WHERE organization_id=:org AND id=:id"
            ),
            {
                "org": str(organization_id),
                "id": delta["membership_id"],
                "minimum": delta.get("expected_version", 1) + 1,
            },
        )
        return result.rowcount, unresolved
    harmless = {
        "report.create",
        "invitation.create",
        "invitation.transition",
        "project.create",
    }
    if operation in harmless and command["status"] == "committed":
        return 0, False
    return 0, True


def _recovery_inputs(organization_id: str, expected_journal_hash: str, confirmed_denials: list[str] | None):
    path = marker_path(organization_id)
    if not path.exists():
        raise AppError(409, "restore_fence_required", "An independent restore fence is required.")
    marker = json.loads(path.read_text())
    manifest = inspect_journal(organization_id)
    if manifest["journal_hash"] != expected_journal_hash:
        raise AppError(412, "journal_changed", "The reviewed journal manifest changed.")
    approved = set(confirmed_denials or [])
    references = {item["reference"] for item in manifest["commands"]}
    if not approved <= references:
        raise AppError(422, "validation_error", "A reviewed denial references an unknown journal command.")
    return path, marker, manifest, approved


def _invalidate_restored_tokens(conn, organization_id: str) -> None:
    conn.execute(
        text("""
        UPDATE sessions SET revoked_at=clock_timestamp() WHERE revoked_at IS NULL AND user_id IN
          (SELECT user_id FROM memberships WHERE organization_id=:org)
    """),
        {"org": str(organization_id)},
    )
    conn.execute(
        text("UPDATE invitations SET state='revoked' WHERE organization_id=:org AND state='pending'"),
        {"org": str(organization_id)},
    )
    conn.execute(
        text("""
        UPDATE outbox_messages SET state=CASE WHEN state='pending' THEN 'failed' ELSE state END,
          failed_at=CASE WHEN state='pending' THEN clock_timestamp() ELSE failed_at END,
          lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
          encrypted_payload=NULL,payload_purged_at=clock_timestamp(),last_error_code='restore_reconciliation'
        WHERE organization_id=:org
    """),
        {"org": str(organization_id)},
    )


def _reconcile_command_set(conn, organization_id: str, marker: dict, manifest: dict, approved: set[str]):
    removed, unresolved = 0, []
    current_catalog_hash = hashlib.sha256(
        journal.canonical(_catalog_manifest(conn, organization_id))
    ).hexdigest()
    if current_catalog_hash != marker["catalog_manifest_hash"]:
        unresolved.append("catalog_manifest_changed")
    for command in manifest["commands"]:
        count, unknown = _apply_restriction(conn, organization_id, command, approved)
        removed += count
        if unknown:
            unresolved.append(command["reference"])
    _invalidate_restored_tokens(conn, organization_id)
    if inspect_journal(organization_id)["journal_hash"] != manifest["journal_hash"]:
        raise AppError(412, "journal_changed", "The journal changed during restore reconciliation.")
    return removed, unresolved


def _persist_restore_outcome(
    conn, organization_id: str, marker: dict, expected_journal_hash: str, removed: int, unresolved: list[str]
):
    opened = not unresolved
    conn.execute(
        text("""
        INSERT INTO migration_controls(organization_id,writer_epoch,write_fenced,baseline_revision)
        VALUES(:org,:epoch,:fenced,'restore-reconciled')
        ON CONFLICT(organization_id) DO UPDATE SET writer_epoch=GREATEST(migration_controls.writer_epoch+1,:epoch),
          write_fenced=:fenced,baseline_revision='restore-reconciled',updated_at=clock_timestamp()
    """),
        {"org": str(organization_id), "epoch": marker["minimum_epoch"] + 1, "fenced": not opened},
    )
    conn.execute(
        text("UPDATE organizations SET status=:status WHERE id=:org"),
        {"org": str(organization_id), "status": "active" if opened else "suspended"},
    )
    audit(
        conn,
        {"actor_key": "service:recovery"},
        organization_id,
        "restore.reconciled",
        "organization",
        organization_id,
        {
            "journal_hash": expected_journal_hash,
            "restriction_count": removed,
            "unresolved_count": len(unresolved),
            "opened": opened,
        },
    )
    return opened


def reconcile_restore(
    organization_id: str, expected_journal_hash: str, confirmed_denials: list[str] | None = None
) -> dict:
    path, marker, manifest, approved = _recovery_inputs(
        organization_id, expected_journal_hash, confirmed_denials
    )
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        organization = required_row(
            conn, "SELECT access_mode FROM organizations WHERE id=:org", {"org": str(organization_id)}
        )
        if organization["access_mode"] != marker["authority"]:
            raise AppError(
                409,
                "restore_authority_changed",
                "Target ownership must be reestablished before opening access.",
            )
        removed, unresolved = _reconcile_command_set(conn, organization_id, marker, manifest, approved)
        opened = _persist_restore_outcome(
            conn, organization_id, marker, expected_journal_hash, removed, unresolved
        )
    if opened:
        path.unlink()
    return {
        "organization_id": str(organization_id),
        "opened": opened,
        "restriction_count": removed,
        "unresolved_references": unresolved,
        "journal_hash": expected_journal_hash,
    }

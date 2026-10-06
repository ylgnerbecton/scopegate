"""Scoped containment and aggregate signals for the local operating rehearsal."""

from sqlalchemy import text

from scopegate import db
from scopegate.config import get_settings
from scopegate.errors import AppError
from scopegate.services.common import audit, check_version
from scopegate.services.invariants import required_row


def snapshot() -> dict:
    with db.transaction() as conn:
        delivery = required_row(
            conn,
            """SELECT
          count(*) FILTER(WHERE state='failed') AS failed_deliveries,
          COALESCE(EXTRACT(EPOCH FROM clock_timestamp()-min(created_at)
            FILTER(WHERE state='pending')),0) AS pending_delivery_oldest_seconds
          FROM outbox_messages""",
        )
        drift = required_row(
            conn,
            """SELECT count(*) AS divergent_decisions
          FROM migration_decisions d JOIN migration_runs r ON r.id=d.run_id
          WHERE r.state IN ('shadow','cutover') AND
            (d.baseline_allowed IS NULL OR d.target_allowed IS NULL OR
             d.baseline_allowed IS DISTINCT FROM d.target_allowed)""",
        )
    return {
        **delivery,
        **drift,
        "pending_delivery_oldest_seconds": float(delivery["pending_delivery_oldest_seconds"]),
        "restore_fences": len(list((get_settings().journal_directory / "restore-fences").glob("*.json"))),
    }


def alerts(values: dict) -> list[dict]:
    rules = [
        ("divergent_decisions", 0, "access_divergence", "backend_owner", "critical"),
        ("pending_delivery_oldest_seconds", 300, "delivery_delay", "delivery_owner", "warning"),
        ("failed_deliveries", 0, "delivery_failed", "delivery_owner", "warning"),
        ("restore_fences", 0, "restore_fenced", "platform_owner", "critical"),
    ]
    return [
        {
            "code": code,
            "owner": owner,
            "severity": severity,
            "runbook": "docs/OPERATIONS.md",
            "observed": values[field],
        }
        for field, threshold, code, owner, severity in rules
        if values[field] > threshold
    ]


def contain(actor: dict, organization_id: str, expected_epoch: int, reason: str) -> dict:
    if len(reason.strip()) < 8:
        raise AppError(422, "validation_error", "An explicit containment reason is required.")
    with db.transaction() as conn:
        db.lock_org(conn, organization_id)
        current = db.row(
            conn,
            "SELECT * FROM migration_controls WHERE organization_id=:org FOR UPDATE",
            {"org": organization_id},
        )
        epoch = current["writer_epoch"] if current else 1
        check_version(epoch, expected_epoch, "writer_epoch_conflict")
        conn.execute(
            text("""INSERT INTO migration_controls(organization_id,writer_epoch,write_fenced,baseline_revision)
          VALUES(:org,:epoch,true,'local-incident') ON CONFLICT(organization_id) DO UPDATE
          SET writer_epoch=:epoch,write_fenced=true,updated_at=clock_timestamp()"""),
            {"org": organization_id, "epoch": epoch + 1},
        )
        audit(
            conn,
            actor,
            organization_id,
            "operations.contained",
            "organization",
            organization_id,
            {"writer_epoch": epoch + 1, "reason": reason},
        )
    return {"organization_id": organization_id, "writer_epoch": epoch + 1, "write_fenced": True}

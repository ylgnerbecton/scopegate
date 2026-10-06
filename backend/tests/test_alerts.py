"""Fault injection proves actionable signals and tenant-specific containment."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import access, enrollment, operations

pytestmark = [pytest.mark.integration, pytest.mark.operations]


def test_delivery_delay_is_actionable_without_metric_identifiers(manager, ids, admin_engine):
    invitation = enrollment.create_invitation(
        manager,
        ids["organizations"]["cedar"],
        {
            "email": "morgan@example.test",
            "expires_in_hours": 72,
            "resources": [
                {"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"]}
            ],
        },
        str(uuid4()),
    )
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE outbox_messages SET created_at=clock_timestamp()-interval '6 minutes' "
                "WHERE invitation_id=:id"
            ),
            {"id": invitation["id"]},
        )
    values = operations.snapshot()
    alert = next(item for item in operations.alerts(values) if item["code"] == "delivery_delay")
    assert alert["owner"] == "delivery_owner" and alert["observed"] > 300
    assert "morgan" not in str(alert) and invitation["id"] not in str(alert)


def test_access_divergence_alert_stops_affected_writes_only(actors, ids, admin_engine):
    org = ids["organizations"]["cedar"]
    with admin_engine.begin() as conn:
        run = db.row(conn, "SELECT id FROM migration_runs LIMIT 1")["id"]
        conn.execute(text("UPDATE migration_runs SET state='shadow' WHERE id=:id"), {"id": run})
        conn.execute(
            text("""INSERT INTO migration_decisions(run_id,organization_id,principal_key,project_key,
          resource_key,action,baseline_allowed,target_allowed,reason)
          VALUES(:run,:org,'unknown','unknown','unknown','resource.use',false,true,'Injected mismatch')"""),
            {"run": run, "org": org},
        )
    alert = next(
        item for item in operations.alerts(operations.snapshot()) if item["code"] == "access_divergence"
    )
    assert alert["owner"] == "backend_owner" and alert["severity"] == "critical"
    fenced = operations.contain(actors["platform"], org, 1, "Investigate injected parity mismatch")
    assert fenced["writer_epoch"] == 2
    with pytest.raises(AppError, match="fenced"):
        access.apply_diff(
            actors["manager"],
            org,
            ids["memberships"]["viewer"],
            ids["projects"]["harbor"],
            {"add": [], "remove": [ids["resources"]["market-pulse"]], "reason": "Attempt during incident"},
            str(uuid4()),
            1,
        )
    assert access.own_decision(
        actors["birch"],
        ids["organizations"]["birch"],
        {"project_id": ids["projects"]["summit"], "resource_id": ids["resources"]["revenue-compass"]},
    )["allowed"]

"""Worker crash, lease, retry, ciphertext and reviewed replay proofs."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import delivery, enrollment

pytestmark = [pytest.mark.integration, pytest.mark.operations]


def queued_message(manager, ids, email="morgan@example.test"):
    body = {
        "email": email,
        "resources": [
            {"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"]}
        ],
    }
    invitation = enrollment.create_invitation(manager, ids["organizations"]["cedar"], body, str(uuid4()))
    with db.transaction() as conn:
        return db.row(conn, "SELECT * FROM outbox_messages WHERE invitation_id=:id", {"id": invitation["id"]})


def test_lease_claim_is_exclusive_and_stale_ack_cannot_finish(manager, ids, admin_engine):
    message = queued_message(manager, ids)
    first = delivery.claim("worker-one", 1)[0]
    assert delivery.claim("worker-two", 1) == []
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE outbox_messages SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"
            ),
            {"id": str(message["id"])},
        )
    second = delivery.claim("worker-two", 1)[0]
    assert second["lease_token"] != first["lease_token"]
    assert delivery.acknowledge(first) is False
    assert delivery.acknowledge(second) is True


def test_crash_after_delivery_reuses_stable_local_receipt(manager, ids, admin_engine, settings):
    queued_message(manager, ids)
    first = delivery.claim("worker-one", 1)[0]
    payload = delivery.current_payload(first)
    delivery.deliver_local(first, payload)
    files = list(settings.mailbox_directory.glob("*.enc"))
    assert len(files) == 1
    assert payload["recipient_email"].encode() not in files[0].read_bytes()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE outbox_messages SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"
            ),
            {"id": str(first["id"])},
        )
    second = delivery.claim("worker-two", 1)[0]
    delivery.deliver_local(second, delivery.current_payload(second))
    assert len(list(settings.mailbox_directory.glob("*.enc"))) == 1
    assert delivery.acknowledge(second) is True
    assert delivery.acknowledge(first) is False
    mailbox = delivery.mailbox(manager, ids["organizations"]["cedar"])
    assert len(mailbox["items"]) == 1 and "#token=" in mailbox["items"][0]["accept_url"]


def test_transient_failure_preserves_pending_then_exhausts_budget(manager, ids, admin_engine):
    message = queued_message(manager, ids)

    def unavailable(message, payload):
        raise TimeoutError("Synthetic transport timeout")

    for index in range(8):
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE outbox_messages SET available_at=clock_timestamp() WHERE id=:id"),
                {"id": str(message["id"])},
            )
        counts = delivery.process_batch("test-worker", 1, unavailable)
        assert counts["claimed"] == 1
        with db.transaction() as conn:
            current = db.row(conn, "SELECT * FROM outbox_messages WHERE id=:id", {"id": str(message["id"])})
        assert current["attempts"] == index + 1
        assert current["state"] == ("failed" if index == 7 else "pending")
    assert delivery.claim("other-worker", 1) == []


def test_poison_ciphertext_is_isolated_and_cannot_replay(manager, ids, admin_engine):
    message = queued_message(manager, ids)
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE outbox_messages SET encrypted_payload=:poison WHERE id=:id"),
            {"id": str(message["id"]), "poison": b"unreadable-ciphertext"},
        )
    counts = delivery.process_batch("test-worker", 1)
    assert counts["failed"] == 1
    with pytest.raises(AppError) as error:
        delivery.replay(
            manager,
            ids["organizations"]["cedar"],
            str(message["id"]),
            "Reviewed retry after key check",
            str(uuid4()),
        )
    assert error.value.code == "replay_unavailable"


def test_reviewed_replay_retains_total_attempts_and_receipt(manager, ids, admin_engine):
    message = queued_message(manager, ids)
    first = delivery.claim("worker-one", 1)[0]
    assert delivery.acknowledge(first, "synthetic_permanent_rejection", permanent=True)
    key = str(uuid4())
    response = delivery.replay(
        manager, ids["organizations"]["cedar"], str(message["id"]), "Reviewed synthetic adapter repair", key
    )
    assert response["replay_generation"] == 1
    assert (
        delivery.replay(
            manager,
            ids["organizations"]["cedar"],
            str(message["id"]),
            "Reviewed synthetic adapter repair",
            key,
        )
        == response
    )
    with db.transaction() as conn:
        current = db.row(conn, "SELECT * FROM outbox_messages WHERE id=:id", {"id": str(message["id"])})
    assert current["attempts"] == 1 and current["generation_attempts"] == 0


def test_purge_removes_ciphertext_and_blocks_later_replay(manager, ids, admin_engine):
    message = queued_message(manager, ids)
    leased = delivery.claim("worker-one", 1)[0]
    delivery.acknowledge(leased, "synthetic_failure", permanent=True)
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE outbox_messages SET failed_at=clock_timestamp()-interval '25 hours' WHERE id=:id"),
            {"id": str(message["id"])},
        )
    assert delivery.purge() == 1
    with db.transaction() as conn:
        current = db.row(
            conn,
            "SELECT encrypted_payload,payload_purged_at FROM outbox_messages WHERE id=:id",
            {"id": str(message["id"])},
        )
    assert current["encrypted_payload"] is None and current["payload_purged_at"] is not None
    with pytest.raises(AppError):
        delivery.replay(
            manager, ids["organizations"]["cedar"], str(message["id"]), "Reviewed retry attempt", str(uuid4())
        )


def test_resend_prevents_stale_pending_message_delivery(manager, ids):
    old = queued_message(manager, ids)
    enrollment.change_invitation(
        manager, ids["organizations"]["cedar"], str(old["invitation_id"]), str(uuid4()), "resend"
    )
    counts = delivery.process_batch("test-worker", 4)
    assert counts["delivered"] == 1
    with db.transaction() as conn:
        old = db.row(conn, "SELECT state FROM outbox_messages WHERE id=:id", {"id": str(old["id"])})
    assert old["state"] == "failed"


def test_mailbox_is_manager_protected_and_scoped(manager, viewer, ids):
    queued_message(manager, ids)
    delivery.process_batch("test-worker", 1)
    with pytest.raises(AppError) as error:
        delivery.mailbox(viewer, ids["organizations"]["cedar"])
    assert error.value.status == 403
    with pytest.raises(AppError) as error:
        delivery.mailbox(manager, ids["organizations"]["birch"])
    assert error.value.status == 404


def test_ciphertext_retention_boundary_is_one_hour(manager, ids, admin_engine, monkeypatch):
    from datetime import timedelta

    first = queued_message(manager, ids)
    leased = delivery.claim("worker-one", 1)[0]
    delivery.acknowledge(leased, "synthetic_failure", permanent=True)
    second = queued_message(manager, ids, email="second@example.test")
    leased = delivery.claim("worker-one", 1)[0]
    delivery.acknowledge(leased, "synthetic_failure", permanent=True)
    with admin_engine.begin() as conn:
        anchor = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
        conn.execute(
            text("UPDATE outbox_messages SET failed_at=:at WHERE id=:id"),
            {"id": str(first["id"]), "at": anchor - timedelta(hours=1, microseconds=1)},
        )
        conn.execute(
            text("UPDATE outbox_messages SET failed_at=:at WHERE id=:id"),
            {"id": str(second["id"]), "at": anchor - timedelta(hours=1)},
        )
    monkeypatch.setattr(db, "clock", lambda conn: anchor)
    assert delivery.purge() == 1
    with db.transaction() as conn:
        first = db.row(
            conn, "SELECT encrypted_payload FROM outbox_messages WHERE id=:id", {"id": str(first["id"])}
        )
        second = db.row(
            conn, "SELECT encrypted_payload FROM outbox_messages WHERE id=:id", {"id": str(second["id"])}
        )
    assert first["encrypted_payload"] is None and second["encrypted_payload"] is not None

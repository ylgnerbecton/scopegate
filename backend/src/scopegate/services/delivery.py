"""Durable leased outbox with a private encrypted local mailbox adapter."""

from __future__ import annotations

import hashlib
import json
import os
import random
import secrets
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from scopegate import db, telemetry
from scopegate.config import get_settings
from scopegate.errors import AppError
from scopegate.services.common import audit, receipt, require_member, save_receipt, serialize
from scopegate.services.identity import token_hash
from scopegate.services.invariants import required_row


def cipher() -> Fernet:
    return Fernet(get_settings().outbox_key.encode())


def enqueue(conn, organization_id: str, invitation_id: str, recipient_email: str, token: str) -> str:
    message_id = str(uuid4())
    payload = {
        "organization_id": str(organization_id),
        "invitation_id": str(invitation_id),
        "recipient_email": recipient_email,
        "subject": "Your Scopegate invitation",
        "accept_url": get_settings().public_origin.rstrip("/") + "/invitations/accept#token=" + token,
    }
    parent = telemetry.capture()
    if parent is not None:
        payload["_traceparent"] = parent
    encrypted = cipher().encrypt(json.dumps(payload).encode())
    conn.execute(
        text("""
        INSERT INTO outbox_messages(id,organization_id,invitation_id,delivery_key,encrypted_payload)
        VALUES(:id,:org,:invite,:key,:payload)
    """),
        {
            "id": message_id,
            "org": str(organization_id),
            "invite": str(invitation_id),
            "key": "invitation:" + str(invitation_id) + ":" + token_hash(token),
            "payload": encrypted,
        },
    )
    return message_id


def _mailbox_dir() -> Path:
    settings = get_settings()
    if settings.environment not in {"local", "test"}:
        raise AppError(503, "delivery_unavailable", "The local mailbox cannot run outside local evaluation.")
    path = Path(settings.mailbox_directory)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def deliver_local(message: dict, payload: dict) -> None:
    """A stable encrypted filename makes this adapter deduplicate its local receipt."""
    folder = _mailbox_dir()
    name = hashlib.sha256(message["delivery_key"].encode()).hexdigest() + ".enc"
    target = folder / name
    public = {key: value for key, value in payload.items() if key != "_traceparent"}
    record = {**public, "id": str(message["id"]), "created_at": serialize(db_message_time(message))}
    encrypted = cipher().encrypt(json.dumps(record).encode())
    temporary = folder / (name + "." + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def db_message_time(message: dict):
    return message["created_at"]


@telemetry.traced("delivery.claim", "outbox")
def claim(owner: str, limit: int = 4) -> list[dict]:
    if not owner or not 1 <= limit <= 4:
        raise ValueError("A worker owner and 1 to 4 delivery slots are required")
    with db.transaction() as conn:
        _finalize_unclaimable(conn)
        candidates = db.rows(
            conn,
            """
            SELECT id FROM outbox_messages
            WHERE state='pending' AND available_at<=clock_timestamp()
              AND generation_attempts<8 AND retry_deadline_at>clock_timestamp()
              AND (lease_expires_at IS NULL OR lease_expires_at<=clock_timestamp())
              AND EXISTS (SELECT 1 FROM invitations i WHERE i.id=outbox_messages.invitation_id
                AND i.organization_id=outbox_messages.organization_id AND i.state='pending'
                AND i.expires_at>clock_timestamp()
                AND outbox_messages.delivery_key='invitation:'||i.id::text||':'||i.token_hash)
            ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT :limit
        """,
            {"limit": limit},
        )
        messages = []
        for candidate in candidates:
            messages.append(
                required_row(
                    conn,
                    """
                UPDATE outbox_messages SET lease_owner=:owner,lease_token=:token,
                  lease_expires_at=clock_timestamp()+interval '30 seconds',
                  attempts=attempts+1,generation_attempts=generation_attempts+1,last_attempt_at=clock_timestamp()
                WHERE id=:id RETURNING *
            """,
                    {"id": str(candidate["id"]), "owner": owner, "token": str(uuid4())},
                )
            )
        return messages


def _finalize_unclaimable(conn) -> None:
    conn.execute(
        text("""
        UPDATE outbox_messages SET state='failed',failed_at=clock_timestamp(),
          last_error_code='retry_budget_exhausted',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
        WHERE id IN (SELECT id FROM outbox_messages WHERE state='pending'
          AND (generation_attempts>=8 OR retry_deadline_at<=clock_timestamp()
            OR NOT EXISTS (SELECT 1 FROM invitations i WHERE i.id=outbox_messages.invitation_id
              AND i.organization_id=outbox_messages.organization_id AND i.state='pending'
              AND i.expires_at>clock_timestamp()
              AND outbox_messages.delivery_key='invitation:'||i.id::text||':'||i.token_hash))
          AND (lease_expires_at IS NULL OR lease_expires_at<=clock_timestamp())
          ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 100)
    """)
    )


def _decrypt_payload(message: dict) -> dict:
    try:
        payload = json.loads(cipher().decrypt(bytes(message["encrypted_payload"])))
        if not isinstance(payload, dict):
            raise ValueError("Invalid envelope")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise AppError(409, "payload_unreadable", "The delivery payload cannot be read.") from exc
    return payload


def current_payload(message: dict, envelope: dict | None = None) -> dict:
    payload = dict(envelope if envelope is not None else _decrypt_payload(message))
    payload.pop("_traceparent", None)
    raw_token = payload.get("accept_url", "").partition("#token=")[2]
    with db.transaction() as conn:
        invitation = required_row(
            conn,
            """
            SELECT token_hash,state,expires_at FROM invitations
            WHERE organization_id=:org AND id=:id
        """,
            {"org": str(message["organization_id"]), "id": str(message["invitation_id"])},
        )
        now = db.clock(conn)
    if (
        not invitation
        or invitation["state"] != "pending"
        or invitation["expires_at"] <= now
        or not secrets.compare_digest(invitation["token_hash"], token_hash(raw_token))
    ):
        raise AppError(409, "invitation_unavailable", "The invitation is no longer available.")
    return payload


@telemetry.traced("delivery.acknowledge", "outbox")
def acknowledge(message: dict, error_code: str | None = None, permanent: bool = False) -> bool:
    exhausted = message["generation_attempts"] >= 8
    terminal = permanent or exhausted
    delay = random.uniform(0, min(60.0, 2 ** min(message["generation_attempts"], 6)))
    with db.transaction() as conn:
        result = conn.execute(
            text("""
            UPDATE outbox_messages SET
              state=:state,delivered_at=CASE WHEN :state='delivered' THEN clock_timestamp() ELSE NULL END,
              failed_at=CASE WHEN :state='failed' THEN clock_timestamp() ELSE NULL END,
              last_error_code=:error,available_at=clock_timestamp()+(:delay * interval '1 second'),
              lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
            WHERE id=:id AND state='pending' AND lease_owner=:owner AND lease_token=:token
              AND replay_generation=:generation AND lease_expires_at>clock_timestamp()
        """),
            {
                "id": str(message["id"]),
                "owner": message["lease_owner"],
                "token": str(message["lease_token"]),
                "generation": message["replay_generation"],
                "state": "delivered" if not error_code else "failed" if terminal else "pending",
                "error": error_code,
                "delay": delay,
            },
        )
        return result.rowcount == 1


def process_batch(owner: str = "local-worker", limit: int = 4, adapter=deliver_local) -> dict:
    counts = {"claimed": 0, "delivered": 0, "failed": 0, "stale": 0}
    for message in claim(owner, limit):
        counts["claimed"] += 1
        counts[_process_message(message, adapter)] += 1
    purge()
    purge_mailbox()
    return counts


def _process_message(message: dict, adapter) -> str:
    try:
        envelope = _decrypt_payload(message)
    except AppError:
        envelope = None
    parent = telemetry.remote_context(envelope.get("_traceparent") if envelope else None)
    with telemetry.span("delivery.attempt", "outbox", parent) as active:
        return _deliver_attempt(message, envelope, adapter, active)


def _deliver_attempt(message: dict, envelope: dict | None, adapter, active) -> str:
    try:
        payload = current_payload(message, envelope)
        with telemetry.span("delivery.adapter", "delivery"):
            adapter(message, payload)
    except AppError as exc:
        telemetry.mark_failed(active)
        accepted = acknowledge(message, exc.code, permanent=True)
        return "failed" if accepted else "stale"
    except (OSError, TimeoutError):
        telemetry.mark_failed(active)
        accepted = acknowledge(message, "adapter_temporarily_unavailable")
        return "failed" if accepted else "stale"
    accepted = acknowledge(message)
    return "delivered" if accepted else "stale"


def mailbox(actor: dict, organization_id: str) -> dict:
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
    messages = []
    for path in sorted(_mailbox_dir().glob("*.enc"), key=lambda value: value.stat().st_mtime, reverse=True)[
        :500
    ]:
        try:
            payload = json.loads(cipher().decrypt(path.read_bytes()))
        except (InvalidToken, ValueError, OSError):
            continue
        if payload.get("organization_id") == str(organization_id):
            messages.append(
                {
                    key: payload[key]
                    for key in ["id", "recipient_email", "subject", "accept_url", "created_at"]
                }
            )
        if len(messages) == 100:
            break
    return {"items": messages}


def replay(actor: dict, organization_id: str, message_id: str, reason: str, key: str) -> dict:
    if len(reason.strip()) < 8:
        raise AppError(422, "validation_error", "A reviewed replay reason is required.")
    with db.transaction() as conn:
        require_member(conn, actor, organization_id, manager=True)
        payload = {"message_id": str(message_id), "reason": reason.strip()}
        stored = receipt(conn, actor, organization_id, "outbox.replay", key, payload)
        if stored:
            return stored
        message = db.row(
            conn,
            "SELECT * FROM outbox_messages WHERE organization_id=:org AND id=:id FOR UPDATE",
            {"org": str(organization_id), "id": str(message_id)},
        )
        if not message or message["state"] != "failed" or message["encrypted_payload"] is None:
            raise AppError(
                409, "replay_unavailable", "Only a failed readable message can be reviewed for replay."
            )
        try:
            json.loads(cipher().decrypt(bytes(message["encrypted_payload"])))
        except (InvalidToken, ValueError, TypeError) as exc:
            raise AppError(
                409, "replay_unavailable", "The retained delivery ciphertext cannot be read."
            ) from exc
        invitation = required_row(
            conn,
            "SELECT state,expires_at FROM invitations WHERE organization_id=:org AND id=:id",
            {"org": str(organization_id), "id": str(message["invitation_id"])},
        )
        if invitation["state"] != "pending" or invitation["expires_at"] <= db.clock(conn):
            raise AppError(409, "replay_unavailable", "The invitation is no longer available.")
        conn.execute(
            text("""
            UPDATE outbox_messages SET state='pending',failed_at=NULL,last_error_code=NULL,
              generation_attempts=0,replay_generation=replay_generation+1,
              available_at=clock_timestamp(),retry_deadline_at=LEAST(clock_timestamp()+interval '30 minutes',:expiry),
              lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE id=:id
        """),
            {"id": str(message_id), "expiry": invitation["expires_at"]},
        )
        audit(
            conn, actor, organization_id, "outbox.replayed", "outbox", message_id, {"reason": reason.strip()}
        )
        response = {
            "id": str(message_id),
            "state": "pending",
            "replay_generation": message["replay_generation"] + 1,
        }
        save_receipt(conn, actor, organization_id, "outbox.replay", key, payload, response)
    return response


def purge(older_than_hours: int = 1) -> int:
    if older_than_hours < 1:
        raise ValueError("Retention must be at least one hour")
    with db.transaction() as conn:
        cutoff = db.clock(conn) - timedelta(hours=older_than_hours)
        result = conn.execute(
            text("""
            UPDATE outbox_messages SET encrypted_payload=NULL,payload_purged_at=clock_timestamp()
            WHERE id IN (SELECT id FROM outbox_messages WHERE state IN ('delivered','failed')
              AND encrypted_payload IS NOT NULL AND COALESCE(delivered_at,failed_at)<:cutoff
              ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 100)
        """),
            {"cutoff": cutoff},
        )
        return result.rowcount


def purge_mailbox(retention_hours: int = 24) -> int:
    if retention_hours < 1:
        raise ValueError("Mailbox retention must be at least one hour")
    cutoff = time.time() - retention_hours * 3600
    removed = 0
    for path in _mailbox_dir().glob("*.enc"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
        if removed == 100:
            break
    return removed

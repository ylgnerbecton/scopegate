"""Shared authority, command receipts and bounded cursor primitives."""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from typing import Any
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from scopegate import db, journal
from scopegate.config import get_settings
from scopegate.errors import AppError

MEMBERSHIP_FIELDS = (
    "id",
    "organization_id",
    "user_id",
    "role",
    "status",
    "kind",
    "expires_at",
    "access_version",
    "can_review_migration",
    "display_name",
    "email",
)
_journal_reference: ContextVar[str | None] = ContextVar("scopegate_command_journal", default=None)


def _safe_delta(payload: dict) -> dict:
    safe_fields = {
        "organization_id",
        "membership_id",
        "project_id",
        "resource_id",
        "resource_ids",
        "expected_version",
        "status",
        "add",
        "remove",
        "initial_manager_user_id",
        "id",
        "impact_token",
        "invitation_id",
        "resources",
        "action",
        "token_hash",
    }
    return serialize({key: value for key, value in payload.items() if key in safe_fields})


def journaled(operation: str, binding: Callable[..., tuple[str, str, dict]]) -> Callable:
    """One narrow boundary places independent I/O outside domain locks.

    The binding returns the exact organization, key and receipt payload. Only
    safe identifiers and access deltas enter the independent local journal.
    """

    def decorate(function: Callable) -> Callable:
        @wraps(function)
        def command(actor: Any, *args: Any, **kwargs: Any) -> Any:
            organization_id, key, payload = binding(actor, *args, **kwargs)
            reference = journal.prepare(
                actor_key(actor),
                organization_id,
                operation,
                key,
                serialize(payload),
                safe_delta=_safe_delta(payload),
            )
            token = _journal_reference.set(reference)
            try:
                response = function(actor, *args, **kwargs)
            except AppError as error:
                journal.outcome(reference, "rejected", {"code": error.code})
                raise
            except Exception:
                journal.outcome(reference, "uncertain", {})
                raise
            else:
                # The use-case transaction has committed before this append.
                journal.outcome(reference, "committed", serialize(response))
                return response
            finally:
                _journal_reference.reset(token)

        return command

    return decorate


def actor_value(actor: Any, key: str, default: Any = None) -> Any:
    return actor.get(key, default) if isinstance(actor, dict) else getattr(actor, key, default)


def actor_key(actor: Any) -> str:
    return actor_value(actor, "actor_key") or f"user:{actor_value(actor, 'user_id')}"


def serialize(value: Any) -> Any:
    return jsonable_encoder(value)


def select_fields(value: dict, fields: tuple[str, ...]) -> dict:
    return serialize({key: value[key] for key in fields if key in value})


def membership_view(value: dict) -> dict:
    return select_fields(value, MEMBERSHIP_FIELDS)


def require_member(conn: Any, actor: Any, organization_id: str, manager: bool = False) -> dict:
    from scopegate.services.recovery import assert_open

    assert_open(str(organization_id))
    membership = db.row(
        conn,
        """
        SELECT m.*, o.status AS organization_status, o.access_mode, u.display_name, u.email
        FROM memberships m JOIN organizations o ON o.id=m.organization_id JOIN users u ON u.id=m.user_id
        WHERE m.organization_id=:org AND m.user_id=:user
    """,
        {"org": str(organization_id), "user": str(actor_value(actor, "user_id"))},
    )
    if not membership:
        raise AppError(404, "organization_not_found", "Organization was not found.")
    now = db.clock(conn)
    inactive = membership["status"] != "active" or membership["organization_status"] != "active"
    expired = membership["expires_at"] is not None and membership["expires_at"] <= now
    if inactive or expired:
        raise AppError(403, "permission_denied", "The membership is inactive or expired.")
    if manager and membership["role"] != "access_manager":
        raise AppError(403, "permission_denied", "An access manager is required.")
    return membership


def require_project(conn: Any, organization_id: str, project_id: str) -> dict:
    project = db.row(
        conn,
        "SELECT * FROM projects WHERE organization_id=:org AND id=:project",
        {"org": str(organization_id), "project": str(project_id)},
    )
    if not project:
        raise AppError(404, "project_not_found", "Project was not found.")
    return project


def enforce_writable(conn: Any, organization_id: str) -> None:
    from scopegate.services.recovery import assert_open

    assert_open(str(organization_id))
    control = db.row(
        conn,
        """
        SELECT o.access_mode, COALESCE(c.write_fenced,false) AS write_fenced
        FROM organizations o LEFT JOIN migration_controls c ON c.organization_id=o.id
        WHERE o.id=:org
    """,
        {"org": str(organization_id)},
    )
    if not control or control["access_mode"] != "target" or control["write_fenced"]:
        raise AppError(409, "writer_fenced", "This organization is fenced for reviewed migration.")


def request_hash(value: Any) -> str:
    raw = json.dumps(serialize(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def literal_search_pattern(query: str) -> str:
    """SQL still binds this value; escaping makes wildcard characters literal."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def validate_key(key: str) -> None:
    if not 8 <= len(key) <= 128:
        raise AppError(422, "validation_error", "Idempotency-Key must contain 8 to 128 characters.")


def receipt(
    conn: Any, actor: Any, organization_id: str, operation: str, key: str, payload: Any
) -> dict | None:
    validate_key(key)
    # Serialize duplicate commands even when the domain operation uses a shared
    # organization lock. Acquire only after all resource and organization locks.
    binding = f"{actor_key(actor)}:{organization_id}:{operation}:{key}"
    conn.execute(text("SELECT pg_advisory_xact_lock(17291,hashtext(:binding))"), {"binding": binding})
    stored = db.row(
        conn,
        """
        SELECT request_hash,response_body FROM command_receipts
        WHERE actor_key=:actor AND organization_id=:org AND operation=:operation
          AND idempotency_key=:key AND expires_at > clock_timestamp()
    """,
        {"actor": actor_key(actor), "org": str(organization_id), "operation": operation, "key": key},
    )
    if stored and stored["request_hash"] != request_hash(payload):
        raise AppError(409, "idempotency_conflict", "The key was already used for different input.")
    return stored["response_body"] if stored else None


def save_receipt(
    conn: Any,
    actor: Any,
    organization_id: str,
    operation: str,
    key: str,
    payload: Any,
    response: dict,
    status: int = 200,
) -> None:
    conn.execute(
        text("""
        INSERT INTO command_receipts(actor_key,organization_id,operation,idempotency_key,
          request_hash,response_status,response_body,expires_at,journal_reference)
        VALUES(:actor,:org,:operation,:key,:hash,:status,CAST(:body AS jsonb),clock_timestamp()+interval '24 hours',:journal)
        ON CONFLICT(actor_key,organization_id,operation,idempotency_key) DO UPDATE
        SET request_hash=EXCLUDED.request_hash,response_status=EXCLUDED.response_status,
            response_body=EXCLUDED.response_body,expires_at=EXCLUDED.expires_at,created_at=clock_timestamp(),
            journal_reference=EXCLUDED.journal_reference
    """),
        {
            "actor": actor_key(actor),
            "org": str(organization_id),
            "operation": operation,
            "key": key,
            "hash": request_hash(payload),
            "status": status,
            "body": json.dumps(serialize(response)),
            "journal": _journal_reference.get(),
        },
    )


def audit(
    conn: Any,
    actor: Any,
    organization_id: str | None,
    action: str,
    target_type: str,
    target_id: str,
    summary: dict,
) -> None:
    user_id = actor_value(actor, "user_id")
    correlation = actor_value(actor, "correlation_id") or str(uuid4())
    conn.execute(
        text("""
        INSERT INTO audit_events(organization_id,actor_kind,actor_user_id,actor_key,
          action,target_type,target_id,safe_change_summary,correlation_id,journal_reference)
        VALUES(:org,:kind,:user,:actor,:action,:type,:target,CAST(:summary AS jsonb),:correlation,:journal)
    """),
        {
            "org": str(organization_id) if organization_id else None,
            "kind": "user" if user_id else "service",
            "user": str(user_id) if user_id else None,
            "actor": actor_key(actor),
            "action": action,
            "type": target_type,
            "target": str(target_id),
            "summary": json.dumps(serialize(summary)),
            "correlation": str(correlation),
            "journal": _journal_reference.get(),
        },
    )


def expected_version(header: str) -> int:
    if not header.startswith('"v') or not header.endswith('"'):
        raise AppError(422, "validation_error", 'If-Match must use the format "v7".')
    try:
        version = int(header[2:-1])
    except ValueError as exc:
        raise AppError(422, "validation_error", "If-Match contains an invalid version.") from exc
    if version < 0:
        raise AppError(422, "validation_error", "Version cannot be negative.")
    return version


def check_version(current: int, expected: int, code: str = "access_version_conflict") -> None:
    if current != expected:
        raise AppError(412, code, "The state changed. Refresh and review it before retrying.")


def _cursor_secret() -> bytes:
    return get_settings().cursor_secret.encode()


def encode_cursor(scope: Any, marker: Any, version: Any = None) -> str:
    body = json.dumps(
        {"scope": request_hash(scope), "last": serialize(marker), "version": version},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signed = body + b"." + hmac.new(_cursor_secret(), body, hashlib.sha256).hexdigest().encode()
    return base64.urlsafe_b64encode(signed).decode().rstrip("=")


def decode_cursor(cursor: str | None, scope: Any, version: Any = None) -> Any:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        body, signature = raw.rsplit(b".", 1)
        expected = hmac.new(_cursor_secret(), body, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        data = json.loads(body)
        if data["scope"] != request_hash(scope):
            raise ValueError("scope mismatch")
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppError(
            422, "validation_error", "The cursor is malformed or belongs to another query."
        ) from exc
    if data.get("version") != version:
        raise AppError(412, "access_version_conflict", "The paged state changed. Refresh the list.")
    return data["last"]


def cursor_uuid(cursor: str | None, scope: Any, version: Any = None) -> str | None:
    marker = decode_cursor(cursor, scope, version)
    if marker is None:
        return None
    try:
        return str(UUID(marker))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AppError(422, "validation_error", "The cursor marker is invalid.") from exc


def page(
    items: list[dict],
    limit: int,
    scope: Any,
    cursor: str | None = None,
    sort_key: str | tuple[str, ...] = "id",
    version: Any = None,
) -> dict:
    """Callers fetch LIMIT limit+1; this helper never hides unbounded reads."""
    if not 1 <= limit <= 100:
        raise AppError(422, "validation_error", "Limit must be between 1 and 100.")
    visible = items[:limit]
    next_cursor = None
    if len(items) > limit:
        marker = (
            [visible[-1][key] for key in sort_key]
            if isinstance(sort_key, tuple)
            else visible[-1][sort_key]
        )
        next_cursor = encode_cursor(scope, marker, version)
    return {"items": serialize(visible), "next_cursor": next_cursor}

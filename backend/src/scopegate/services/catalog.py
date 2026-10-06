"""Publisher content remains independent of tenant entitlement and grants."""

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from scopegate import db
from scopegate.errors import AppError
from scopegate.services.common import (
    actor_key,
    actor_value,
    audit,
    cursor_uuid,
    literal_search_pattern,
    page,
    request_hash,
    require_member,
    require_project,
    serialize,
    validate_key,
)


def list_resources(
    actor: Any,
    organization_id: str,
    project_id: str,
    locale: str,
    query: str,
    view: str,
    limit: int,
    cursor: str | None,
) -> dict:
    scope = ["resources", organization_id, project_id, actor_value(actor, "user_id"), locale, query, view]
    marker = cursor_uuid(cursor, scope)
    with db.transaction() as conn:
        member = require_member(conn, actor, organization_id, manager=view == "entitled")
        require_project(conn, organization_id, project_id)
        items = db.rows(
            conn,
            """
            SELECT r.id,r.external_key,r.catalog_version,r.status,
              localized.title,localized.description,localized.locale,
              COALESCE(localized.tags,'[]'::jsonb) AS tags,
              COALESCE(localized.locale<>:locale,false) AS fallback_used
            FROM project_resources pr JOIN projects p ON p.organization_id=pr.organization_id AND p.id=pr.project_id
            JOIN organizations o ON o.id=pr.organization_id JOIN resources r ON r.id=pr.resource_id
            LEFT JOIN resource_grants g ON g.organization_id=pr.organization_id AND g.project_id=pr.project_id
              AND g.resource_id=pr.resource_id AND g.membership_id=:member
            LEFT JOIN LATERAL (
              SELECT l.title,l.description,l.locale,l.tags FROM resource_localizations l WHERE l.resource_id=r.id
              ORDER BY CASE WHEN l.locale=:locale THEN 0 WHEN l.locale=o.default_locale THEN 1
                WHEN l.locale='en' THEN 2 ELSE 3 END,l.locale LIMIT 1
            ) localized ON true
            WHERE pr.organization_id=:org AND pr.project_id=:project
              AND (:view='entitled' OR (g.state='active' AND pr.status='active' AND r.status='published' AND p.status='active'))
              AND (CAST(:marker AS uuid) IS NULL OR r.id>CAST(:marker AS uuid))
              AND (r.external_key ILIKE :search ESCAPE '\\' OR COALESCE(localized.title,'') ILIKE :search ESCAPE '\\')
            ORDER BY r.id LIMIT :limit
        """,
            {
                "org": organization_id,
                "project": project_id,
                "member": str(member["id"]),
                "locale": locale,
                "view": view,
                "search": literal_search_pattern(query),
                "marker": marker,
                "limit": limit + 1,
            },
        )
    return page(items, limit, scope)


def _catalog_receipt(conn: Any, actor: Any, external_key: str, key: str, body: dict) -> dict | None:
    stored = db.row(
        conn,
        """
        SELECT request_hash,response_body FROM catalog_receipts WHERE actor_key=:actor
          AND external_key=:external AND idempotency_key=:key AND expires_at>clock_timestamp()
    """,
        {"actor": actor_key(actor), "external": external_key, "key": key},
    )
    if stored and stored["request_hash"] != request_hash(body):
        raise AppError(409, "idempotency_conflict", "The publication key was reused with different input.")
    return stored["response_body"] if stored else None


def _validate_localizations(localizations: list[dict]) -> None:
    locales = [item["locale"] for item in localizations]
    if len(set(locales)) != len(locales):
        raise AppError(422, "validation_error", "Each localization must have a unique locale.")
    for localization in localizations:
        tags = localization["tags"]
        if len(set(tags)) != len(tags):
            raise AppError(422, "validation_error", "Localization tags must be unique.")


def _validate_publication(current: dict | None, body: dict) -> None:
    expected = current["catalog_version"] if current else 0
    if body["expected_version"] != expected or body["version"] <= expected:
        raise AppError(
            409, "catalog_version_conflict", "Publication must advance the current catalog version."
        )
    if current and current["status"] == "archived" and body["status"] != "archived":
        raise AppError(
            409,
            "resource_archive_terminal",
            "Archival is terminal; publish a new stable key for replacement.",
        )
    _validate_localizations(body["localizations"])


def _write_resource(conn: Any, resource_id: str, external_key: str, current: dict | None, body: dict) -> None:
    avatar = body.get("avatar_url", current.get("avatar_url") if current else None)
    conn.execute(
        text("""
        INSERT INTO resources(id,external_key,catalog_version,status,avatar_url)
        VALUES(:id,:external,:version,:status,:avatar)
        ON CONFLICT(external_key) DO UPDATE SET catalog_version=EXCLUDED.catalog_version,
          status=EXCLUDED.status,avatar_url=EXCLUDED.avatar_url,updated_at=clock_timestamp()
    """),
        {
            "id": resource_id,
            "external": external_key,
            "version": body["version"],
            "status": body["status"],
            "avatar": str(avatar) if avatar is not None else None,
        },
    )
    for localization in body["localizations"]:
        params = {
            "resource": resource_id,
            "locale": localization["locale"],
            "title": localization["title"],
            "description": localization.get("description"),
            "clear_description": "description" in localization,
            "tags": json.dumps(localization["tags"]),
        }
        conn.execute(
            text("""
            INSERT INTO resource_localizations(resource_id,locale,title,description,tags)
            VALUES(:resource,:locale,:title,:description,CAST(:tags AS jsonb))
            ON CONFLICT(resource_id,locale) DO UPDATE SET title=EXCLUDED.title,tags=EXCLUDED.tags,
              description=CASE WHEN :clear_description THEN EXCLUDED.description ELSE resource_localizations.description END
        """),
            params,
        )


def resource_view(conn: Any, resource_id: str) -> dict:
    resource = db.row(
        conn,
        """
        SELECT r.id,r.external_key,r.catalog_version,r.status,l.title,l.description,l.locale,
          COALESCE(l.tags,'[]'::jsonb) AS tags,false AS fallback_used FROM resources r
        LEFT JOIN LATERAL(SELECT * FROM resource_localizations WHERE resource_id=r.id
          ORDER BY CASE WHEN locale='en' THEN 0 ELSE 1 END,locale LIMIT 1) l ON true WHERE r.id=:id
    """,
        {"id": resource_id},
    )
    return serialize(resource)


def publish(actor: Any, external_key: str, body: dict, key: str) -> dict:
    validate_key(key)
    with db.transaction() as conn:
        # Serialize creation for an external key that has no row yet. It is a
        # catalog namespace; no tenant lock or permission mutation follows it.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(17292,hashtext(:external))"), {"external": external_key}
        )
        current = db.row(
            conn,
            "SELECT * FROM resources WHERE external_key=:external FOR UPDATE",
            {"external": external_key},
        )
        stored = _catalog_receipt(conn, actor, external_key, key, body)
        if stored is not None:
            return stored
        _validate_publication(current, body)
        resource_id = str(current["id"]) if current else str(uuid4())
        _write_resource(conn, resource_id, external_key, current, body)
        response = resource_view(conn, resource_id)
        conn.execute(
            text("""
            INSERT INTO catalog_receipts(actor_key,external_key,idempotency_key,request_hash,response_body,expires_at)
            VALUES(:actor,:external,:key,:hash,CAST(:body AS jsonb),clock_timestamp()+interval '24 hours')
            ON CONFLICT(actor_key,external_key,idempotency_key) DO UPDATE SET request_hash=EXCLUDED.request_hash,
              response_body=EXCLUDED.response_body,expires_at=EXCLUDED.expires_at
        """),
            {
                "actor": actor_key(actor),
                "external": external_key,
                "key": key,
                "hash": request_hash(body),
                "body": json.dumps(response),
            },
        )
        audit(
            conn,
            actor,
            None,
            "catalog.published",
            "resource",
            resource_id,
            {
                "external_key": external_key,
                "catalog_version": body["version"],
                "status": body["status"],
                "locales": [item["locale"] for item in body["localizations"]],
            },
        )
        return response

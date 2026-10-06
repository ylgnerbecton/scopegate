"""Validate actual transport responses against the independent canonical contract."""

import json
from pathlib import Path
from time import time
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from sqlalchemy import text

from scopegate.config import get_settings
from scopegate.seed import USERS
from scopegate.services import delivery, identity

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "specs/contracts/openapi.json").read_text())


def assert_contract(response, route: str, method: str, expected: int):
    assert response.status_code == expected, response.text
    specification = CONTRACT["paths"][route][method]["responses"][str(expected)]
    if "$ref" in specification:
        specification = CONTRACT["components"]["responses"][specification["$ref"].split("/")[-1]]
    if "content" in specification:
        schema = specification["content"]["application/json"]["schema"]
        Draft202012Validator({**CONTRACT, **schema}, format_checker=FormatChecker()).validate(response.json())
    assert response.headers.get("x-correlation-id")
    return (
        response.json()
        if response.content and "application/json" in response.headers.get("content-type", "")
        else None
    )


def sign_in(client, subject="manager-cedar"):
    emails = {
        "manager-cedar": "amelia@example.test",
        "viewer-cedar": "jonah@example.test",
        "staff-operator": "rowan@example.test",
        "guest-invite": "morgan@example.test",
        "manager-birch": "ellis@example.test",
    }
    opaque = identity.create_session(
        {
            "iss": get_settings().oidc_issuer,
            "sub": subject,
            "email": emails[subject],
            "email_verified": True,
            "name": subject,
            "auth_time": int(time()),
        }
    )
    client.cookies.set(identity.SESSION_COOKIE, opaque)
    return {
        "Origin": get_settings().public_origin,
        "X-CSRF-Token": identity.csrf_value(opaque),
        "Idempotency-Key": str(uuid4()),
    }


def test_openapi_route_and_request_surface_matches():
    from scopegate.main import app

    generated = app.openapi()
    validate(CONTRACT)
    actual = {
        (path, method): operation
        for path, methods in generated["paths"].items()
        for method, operation in methods.items()
    }
    expected = {
        (path, method): operation
        for path, methods in CONTRACT["paths"].items()
        for method, operation in methods.items()
    }
    assert set(actual) == set(expected)
    for key, canonical in expected.items():
        operation = actual[key]
        assert operation["operationId"] == canonical["operationId"]
        params = {(item["in"], item["name"]): item for item in operation.get("parameters", [])}
        for item in canonical.get("parameters", []):
            if "$ref" in item:
                item = CONTRACT["components"]["parameters"][item["$ref"].split("/")[-1]]
            assert (item["in"], item["name"]) in params, (key, item["name"])
            if item.get("required"):
                assert params[(item["in"], item["name"])].get("required")
        if "requestBody" in canonical:
            assert operation["requestBody"]["required"] == canonical["requestBody"]["required"]


@pytest.mark.integration
def test_http_workspace_and_grant_contract(client, ids):
    headers = sign_in(client)
    org = ids["organizations"]["cedar"]
    project = ids["projects"]["harbor"]
    member = ids["memberships"]["viewer"]
    base = "/api/v1/organizations/{organization_id}"
    routes = [
        "/api/v1/me",
        "/api/v1/organizations",
        base,
        base + "/projects",
        base + "/memberships",
        base + "/audit-events",
        base + "/invitations",
        base + "/mailbox",
        base + "/projects/{project_id}/resources",
        base + "/memberships/{membership_id}/projects/{project_id}/grants",
    ]
    for route in routes:
        path = route.format(organization_id=org, project_id=project, membership_id=member)
        assert_contract(client.get(path), route, "get", 200)
    route = base + "/memberships/{membership_id}/projects/{project_id}/grants"
    path = route.format(organization_id=org, project_id=project, membership_id=member)
    response = client.patch(
        path,
        json={"add": [ids["resources"]["audience-atlas"]], "remove": [], "reason": "Reviewed resource scope"},
        headers={**headers, "If-Match": '"v1"'},
    )
    assert_contract(response, route, "patch", 200)
    status_route = base + "/memberships/{membership_id}"
    status_path = status_route.format(organization_id=org, membership_id=member)
    assert_contract(
        client.patch(
            status_path,
            json={"status": "suspended"},
            headers={**headers, "Idempotency-Key": str(uuid4()), "If-Match": '"v2"'},
        ),
        status_route,
        "patch",
        200,
    )
    assert_contract(
        client.post(
            base.format(organization_id=org) + "/projects",
            json={"name": "Launch"},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        ),
        base + "/projects",
        "post",
        201,
    )
    assert_contract(client.post("/api/v1/logout", headers=headers), "/api/v1/logout", "post", 204)
    assert_contract(client.get("/api/v1/me"), "/api/v1/me", "get", 401)


@pytest.mark.integration
def test_http_invitation_delivery_and_recipient_contract(client, ids):
    headers = sign_in(client)
    org = ids["organizations"]["cedar"]
    route = "/api/v1/organizations/{organization_id}/invitations"
    path = route.format(organization_id=org)
    body = {
        "email": "morgan@example.test",
        "expires_in_hours": 72,
        "resources": [
            {"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"]}
        ],
    }
    invitation = assert_contract(client.post(path, json=body, headers=headers), route, "post", 201)
    delivery.process_batch()
    mailbox = assert_contract(
        client.get(f"/api/v1/organizations/{org}/mailbox"),
        "/api/v1/organizations/{organization_id}/mailbox",
        "get",
        200,
    )
    token = urlparse(mailbox["items"][0]["accept_url"]).fragment.split("token=")[1]
    recipient_headers = sign_in(client, "guest-invite")
    assert_contract(
        client.post("/api/v1/invitations/preview", json={"token": token}, headers=recipient_headers),
        "/api/v1/invitations/preview",
        "post",
        200,
    )
    accepted = assert_contract(
        client.post("/api/v1/invitations/accept", json={"token": token}, headers=recipient_headers),
        "/api/v1/invitations/accept",
        "post",
        200,
    )
    assert accepted["user_id"] == USERS["guest-invite"]
    assert_contract(
        client.post("/api/v1/invitations/accept", json={"token": token}, headers=recipient_headers),
        "/api/v1/invitations/accept",
        "post",
        200,
    )
    assert invitation["state"] == "pending"


@pytest.mark.integration
def test_http_protected_reports_and_scoped_negative_matrix(client, ids):
    headers = sign_in(client, "viewer-cedar")
    org, project = ids["organizations"]["cedar"], ids["projects"]["harbor"]
    base = f"/api/v1/organizations/{org}"
    route = "/api/v1/organizations/{organization_id}/projects/{project_id}/report-configs"
    report = assert_contract(
        client.post(
            f"{base}/projects/{project}/report-configs",
            json={"name": "Protected view", "resource_ids": [ids["resources"]["market-pulse"]]},
            headers=headers,
        ),
        route,
        "post",
        201,
    )
    assert_contract(
        client.get(f"{base}/projects/{project}/report-configs/{report['id']}"),
        route + "/{report_config_id}",
        "get",
        200,
    )
    decision_route = "/api/v1/organizations/{organization_id}/access-decisions"
    assert_contract(
        client.post(
            base + "/access-decisions",
            json={"project_id": project, "resource_id": ids["resources"]["market-pulse"]},
            headers=headers,
        ),
        decision_route,
        "post",
        200,
    )
    # Every customer read surface conceals foreign ownership before returning metadata.
    foreign = ids["organizations"]["birch"]
    templates = [
        "",
        "/projects",
        "/memberships",
        "/audit-events",
        "/invitations",
        "/mailbox",
        "/projects/{project_id}/resources",
        "/memberships/{membership_id}/projects/{project_id}/grants",
        "/projects/{project_id}/report-configs/{report_config_id}",
        "/migration-runs",
    ]
    for suffix in templates:
        template = "/api/v1/organizations/{organization_id}" + suffix
        path = template.format(
            organization_id=foreign,
            project_id=ids["projects"]["summit"],
            membership_id=ids["memberships"]["birch_manager"],
            report_config_id=report["id"],
        )
        result = assert_contract(client.get(path), template, "get", 404)
        assert "Birch" not in json.dumps(result) and "ellis" not in json.dumps(result)
    resources = "/api/v1/organizations/{organization_id}/projects/{project_id}/resources"
    assert_contract(client.get(f"{base}/projects/{project}/resources?view=entitled"), resources, "get", 403)


@pytest.mark.integration
def test_http_explicit_reviewer_and_platform_contract(client, ids):
    sign_in(client, "staff-operator")
    org = ids["organizations"]["cedar"]
    route = "/api/v1/organizations/{organization_id}/migration-runs"
    runs = assert_contract(client.get(route.format(organization_id=org)), route, "get", 200)
    run = runs["items"][0]["id"]
    items = route + "/{run_id}/items"
    assert_contract(client.get(items.format(organization_id=org, run_id=run)), items, "get", 200)
    manifest = route + "/{run_id}/manifest"
    assert_contract(client.get(manifest.format(organization_id=org, run_id=run)), manifest, "get", 200)
    platform_headers = {
        "Authorization": f"Bearer {get_settings().platform_key}",
        "Idempotency-Key": str(uuid4()),
    }
    organization = assert_contract(
        client.post(
            "/api/v1/platform/organizations",
            json={
                "id": str(uuid4()),
                "name": "Willow Works",
                "initial_manager_user_id": USERS["guest-invite"],
            },
            headers=platform_headers,
        ),
        "/api/v1/platform/organizations",
        "post",
        201,
    )
    assert organization["name"] == "Willow Works"


@pytest.mark.security
@pytest.mark.integration
def test_csrf_body_caps_and_auth_headers_are_not_identity(client, ids):
    org = ids["organizations"]["cedar"]
    assert (
        client.get(f"/api/v1/organizations/{org}", headers={"X-User-ID": USERS["manager-cedar"]}).status_code
        == 401
    )
    sign_in(client)
    route = "/api/v1/organizations/{organization_id}/projects"
    assert_contract(
        client.post(
            route.format(organization_id=org),
            json={"name": "Unsafe"},
            headers={"Origin": "https://foreign.example", "Idempotency-Key": str(uuid4())},
        ),
        route,
        "post",
        403,
    )
    assert client.post(route.format(organization_id=org), content=b"x" * 65537).status_code == 413
    assert client.get("/metrics").status_code == 401
    metric = client.get("/metrics", headers={"Authorization": f"Bearer {get_settings().platform_key}"})
    assert metric.status_code == 200
    assert b"@example.test" not in metric.content and org.encode() not in metric.content


@pytest.mark.security
@pytest.mark.integration
def test_runtime_role_cannot_edit_audit_or_ddl(engine):
    from sqlalchemy.exc import DBAPIError

    for statement in [
        "UPDATE audit_events SET action='changed'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
        "CREATE TABLE forbidden(id integer)",
    ]:
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text(statement))


@pytest.mark.security
@pytest.mark.integration
def test_database_rejects_foreign_project_associations(engine, ids):
    from sqlalchemy.exc import DBAPIError

    values = {
        "org": ids["organizations"]["cedar"], "project": ids["projects"]["summit"],
        "resource": ids["resources"]["market-pulse"], "member": ids["memberships"]["viewer"],
        "user": ids["users"]["viewer-cedar"],
    }
    statements = [
        "INSERT INTO project_resources(organization_id,project_id,resource_id) VALUES(:org,:project,:resource)",
        "INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id) VALUES(:org,:member,:project,:resource)",
        "INSERT INTO report_configs(organization_id,project_id,name,created_by) VALUES(:org,:project,'Foreign project',:user)",
    ]
    for statement in statements:
        with pytest.raises(DBAPIError) as failure:
            with engine.begin() as connection:
                connection.execute(text(statement), values)
        assert failure.value.orig.sqlstate == "23503"


@pytest.mark.security
@pytest.mark.integration
def test_runtime_password_cannot_authenticate_as_database_administrator(engine):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    with engine.connect() as connection:
        flags = connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        assert not any(flags)
    administrator = create_engine(make_url(get_settings().database_url).set(username="postgres"),
                                  connect_args={"connect_timeout": 1})
    try:
        with pytest.raises(OperationalError):
            with administrator.connect():
                pytest.fail("The runtime credential authenticated as database administrator")
    finally:
        administrator.dispose()


@pytest.mark.security
@pytest.mark.integration
def test_customer_cannot_promote_membership_role(client, ids):
    headers = sign_in(client)
    org, member = ids["organizations"]["cedar"], ids["memberships"]["viewer"]
    route = "/api/v1/organizations/{organization_id}/memberships/{membership_id}"
    path = route.format(organization_id=org, membership_id=member)
    rejected = assert_contract(
        client.patch(path, json={"status": "active", "role": "access_manager"},
                     headers={**headers, "If-Match": '"v1"'}), route, "patch", 422,
    )
    assert rejected["error"]["code"] == "validation_error"
    members = client.get(f"/api/v1/organizations/{org}/memberships").json()["items"]
    current = next(item for item in members if item["id"] == member)
    assert current["role"] == "viewer" and current["access_version"] == 1


@pytest.mark.integration
def test_http_publisher_and_reviewed_entitlement_contract(client, ids):
    settings = get_settings()
    publisher = {"Authorization": f"Bearer {settings.catalog_key}", "Idempotency-Key": str(uuid4())}
    route = "/api/v1/catalog/resources/{external_key}"
    published = assert_contract(
        client.put("/api/v1/catalog/resources/new-synthetic-view", headers=publisher, json={
            "expected_version": 0, "version": 1, "status": "published",
            "localizations": [{"locale": "en", "title": "New view", "tags": []}],
        }), route, "put", 200,
    )
    assert published["catalog_version"] == 1
    org, project, resource = ids["organizations"]["cedar"], ids["projects"]["harbor"], ids["resources"]["market-pulse"]
    template = "/api/v1/organizations/{organization_id}/projects/{project_id}/entitlements/{resource_id}"
    path = template.format(organization_id=org, project_id=project, resource_id=resource)
    platform = {"Authorization": f"Bearer {settings.platform_key}"}
    for desired in ["disabled", "active"]:
        impact = assert_contract(client.get(path + "/impact", params={"desired_status": desired}, headers=platform), template + "/impact", "get", 200)
        changed = assert_contract(client.put(path, headers={**platform, "Idempotency-Key": str(uuid4()), "If-Match": f'"v{impact["entitlement_version"]}"'},
            json={"status": desired, "impact_token": impact["impact_token"], "reason": "Reviewed contract transition"}), template, "put", 200)
        assert changed["status"] == desired
    sign_in(client, "viewer-cedar")
    visible = client.get(f"/api/v1/organizations/{org}/projects/{project}/resources").json()["items"]
    assert not visible, "Reenable must not resurrect a revoked grant"


@pytest.mark.integration
def test_http_invitation_lifecycle_and_ledger_resolution_contract(client, ids, admin_engine):
    headers = sign_in(client)
    org = ids["organizations"]["cedar"]
    base = "/api/v1/organizations/{organization_id}"
    path = base.format(organization_id=org)
    invitation = assert_contract(client.post(path + "/invitations", headers=headers, json={
        "email": "morgan@example.test", "resources": [{"project_id": ids["projects"]["harbor"], "resource_id": ids["resources"]["market-pulse"]}],
    }), base + "/invitations", "post", 201)
    with admin_engine.begin() as conn:
        message = conn.execute(text("UPDATE outbox_messages SET state='failed',failed_at=clock_timestamp(),last_error_code='adapter_temporarily_unavailable' WHERE invitation_id=:invite RETURNING id"), {"invite": invitation["id"]}).scalar_one()
    replay = assert_contract(client.post(path + f"/outbox/{message}/replay", headers={**headers, "Idempotency-Key": str(uuid4())}, json={"reason": "Reviewed local delivery recovery"}), base + "/outbox/{message_id}/replay", "post", 200)
    assert replay["replay_generation"] == 1
    resent = assert_contract(client.post(path + f'/invitations/{invitation["id"]}/resend', headers={**headers, "Idempotency-Key": str(uuid4())}), base + "/invitations/{invitation_id}/resend", "post", 201)
    assert_contract(client.post(path + f'/invitations/{resent["id"]}/revoke', headers={**headers, "Idempotency-Key": str(uuid4())}), base + "/invitations/{invitation_id}/revoke", "post", 200)
    headers = sign_in(client, "staff-operator")
    run = client.get(path + "/migration-runs").json()["items"][0]["id"]
    item = client.get(path + f"/migration-runs/{run}/items").json()["items"][0]
    assert_contract(client.patch(path + f'/migration-runs/{run}/items/{item["id"]}',
        headers={**headers, "If-Match": f'"v{item["review_version"]}"'},
        json={"outcome": "review_required", "decision_reason": "A scoped owner decision remains required"}),
        base + "/migration-runs/{run_id}/items/{ledger_id}", "patch", 200)

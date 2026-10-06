"""Deterministic, synthetic product data. No private fixtures or credentials."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from scopegate.config import get_settings


def identifier(prefix: int, index: int) -> str:
    return f"{prefix}0000000-0000-4000-8000-{index:012d}"


USERS = {
    key: identifier(1, n)
    for n, key in enumerate(
        ["manager-cedar", "viewer-cedar", "staff-operator", "guest-invite", "manager-birch"], 1
    )
}
ORGS = {"cedar": identifier(2, 1), "birch": identifier(2, 2)}
PROJECTS = {"harbor": identifier(3, 1), "grove": identifier(3, 2), "summit": identifier(3, 3)}
RESOURCES = {
    key: identifier(4, n)
    for n, key in enumerate(["market-pulse", "audience-atlas", "growth-signals", "revenue-compass"], 1)
}
MEMBERSHIPS = {
    "manager": identifier(5, 1),
    "viewer": identifier(5, 2),
    "operator": identifier(5, 3),
    "birch_manager": identifier(5, 4),
    "birch_operator": identifier(5, 5),
}


def _second_staff_assignment(conn) -> None:
    conn.execute(
        text("""INSERT INTO memberships(id,organization_id,user_id,role,kind,expires_at,
      assignment_reason,can_review_migration) VALUES(:id,:org,:user,'access_manager','staff',
      clock_timestamp()+interval '7 days','Synthetic workspace support',true) ON CONFLICT DO NOTHING"""),
        {"id": MEMBERSHIPS["birch_operator"], "org": ORGS["birch"], "user": USERS["staff-operator"]},
    )


def _seed_accounts(conn) -> None:
    accounts = [
        ("manager-cedar", "Amelia Brooks", "amelia@example.test"),
        ("viewer-cedar", "Jonah Reed", "jonah@example.test"),
        ("staff-operator", "Rowan Vale", "rowan@example.test"),
        ("guest-invite", "Morgan Lane", "morgan@example.test"),
        ("manager-birch", "Ellis Park", "ellis@example.test"),
    ]
    for subject, name, email in accounts:
        conn.execute(
            text(
                "INSERT INTO users(id,issuer,subject,email,display_name) VALUES(:id,:issuer,:sub,:email,:name)"
            ),
            {
                "id": USERS[subject],
                "issuer": get_settings().oidc_issuer,
                "sub": subject,
                "email": email,
                "name": name,
            },
        )


def _seed_workspaces(conn) -> None:
    for key, name in [("cedar", "Cedar Studio"), ("birch", "Birch Labs")]:
        conn.execute(
            text("INSERT INTO organizations(id,name) VALUES(:id,:name)"), {"id": ORGS[key], "name": name}
        )
    for key, organization, name in [
        ("harbor", "cedar", "Harbor"),
        ("grove", "cedar", "Grove"),
        ("summit", "birch", "Summit"),
    ]:
        conn.execute(
            text("INSERT INTO projects(id,organization_id,name) VALUES(:id,:org,:name)"),
            {"id": PROJECTS[key], "org": ORGS[organization], "name": name},
        )


def _seed_memberships(conn) -> None:
    assignments = [
        ("manager", "cedar", "manager-cedar", "access_manager", "customer"),
        ("viewer", "cedar", "viewer-cedar", "viewer", "customer"),
        ("operator", "cedar", "staff-operator", "access_manager", "staff"),
        ("birch_manager", "birch", "manager-birch", "access_manager", "customer"),
    ]
    for key, organization, user, role, kind in assignments:
        conn.execute(
            text("""INSERT INTO memberships(id,organization_id,user_id,role,kind,expires_at,
          assignment_reason,can_review_migration) VALUES(:id,:org,:user,:role,:kind,:expires,:reason,:review)"""),
            {
                "id": MEMBERSHIPS[key],
                "org": ORGS[organization],
                "user": USERS[user],
                "role": role,
                "kind": kind,
                "expires": datetime.now(UTC) + timedelta(days=7) if kind == "staff" else None,
                "reason": "Synthetic migration rehearsal" if kind == "staff" else None,
                "review": kind == "staff",
            },
        )


def _seed_catalog(conn) -> None:
    content = [
        (
            "market-pulse",
            "Market pulse",
            "Understand demand, momentum and category movement.",
            ["Markets", "Trends"],
        ),
        (
            "audience-atlas",
            "Audience atlas",
            "Explore segments, preferences and audience overlap.",
            ["Audience", "Research"],
        ),
        (
            "growth-signals",
            "Growth signals",
            "Track acquisition quality and retention opportunities.",
            ["Growth", "Retention"],
        ),
        (
            "revenue-compass",
            "Revenue compass",
            "Monitor revenue composition and commercial performance.",
            ["Revenue", "Strategy"],
        ),
    ]
    for key, title, description, tags in content:
        conn.execute(
            text("INSERT INTO resources(id,external_key,catalog_version) VALUES(:id,:key,1)"),
            {"id": RESOURCES[key], "key": key},
        )
        locales = [
            ("en", title, description),
            (
                "pt",
                {
                    "market-pulse": "Pulso de mercado",
                    "audience-atlas": "Atlas de público",
                    "growth-signals": "Sinais de crescimento",
                    "revenue-compass": "Bússola de receita",
                }[key],
                "Explore dados e decisões com acesso explícito por projeto.",
            ),
        ]
        for locale, localized, detail in locales:
            conn.execute(
                text("""INSERT INTO resource_localizations(resource_id,locale,title,description,tags)
              VALUES(:id,:locale,:title,:description,CAST(:tags AS jsonb))"""),
                {
                    "id": RESOURCES[key],
                    "locale": locale,
                    "title": localized,
                    "description": detail,
                    "tags": json.dumps(tags),
                },
            )


def _seed_access(conn) -> None:
    for project, organization, keys in [
        ("harbor", "cedar", list(RESOURCES)),
        ("grove", "cedar", ["market-pulse", "growth-signals"]),
        ("summit", "birch", ["market-pulse", "revenue-compass"]),
    ]:
        for key in keys:
            conn.execute(
                text(
                    "INSERT INTO project_resources(organization_id,project_id,resource_id) VALUES(:org,:project,:resource)"
                ),
                {"org": ORGS[organization], "project": PROJECTS[project], "resource": RESOURCES[key]},
            )
    for member, organization, project, keys in [
        ("manager", "cedar", "harbor", list(RESOURCES)[:3]),
        ("viewer", "cedar", "harbor", ["market-pulse"]),
        ("manager", "cedar", "grove", ["growth-signals"]),
        ("birch_manager", "birch", "summit", ["revenue-compass"]),
    ]:
        for key in keys:
            conn.execute(
                text("""INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id)
              VALUES(:org,:member,:project,:resource)"""),
                {
                    "org": ORGS[organization],
                    "member": MEMBERSHIPS[member],
                    "project": PROJECTS[project],
                    "resource": RESOURCES[key],
                },
            )


def seed(conn) -> dict:
    if conn.execute(text("SELECT 1 FROM organizations WHERE id=:id"), {"id": ORGS["cedar"]}).scalar():
        _second_staff_assignment(conn)
        return fixtures()
    _seed_accounts(conn)
    _seed_workspaces(conn)
    _seed_memberships(conn)
    _seed_catalog(conn)
    _seed_access(conn)
    # Migration examples are review-only and never switch the demo authority.
    from scopegate.services.migration import seed_demo_migration

    seed_demo_migration(conn, ORGS["cedar"], USERS["staff-operator"])
    _second_staff_assignment(conn)
    return fixtures()


def fixtures() -> dict:
    return {
        "users": USERS.copy(),
        "organizations": ORGS.copy(),
        "projects": PROJECTS.copy(),
        "resources": RESOURCES.copy(),
        "memberships": MEMBERSHIPS.copy(),
    }

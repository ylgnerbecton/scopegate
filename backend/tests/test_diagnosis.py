"""Source-neutral PostgreSQL containment rehearsals over temporary fixtures."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from scopegate.errors import AppError
from scopegate.services import compatibility

TABLES = (
    "compat_assignments",
    "compat_users",
    "compat_resources",
    "compat_denied_addresses",
    "compat_organizations",
)


@pytest.fixture
def compatibility_conn(engine):
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text("""
                CREATE TEMP TABLE compat_organizations(id uuid PRIMARY KEY,name text,resource_keys text,locale text);
                CREATE TEMP TABLE compat_denied_addresses(email text PRIMARY KEY);
                CREATE TEMP TABLE compat_users(id uuid PRIMARY KEY,email text NOT NULL UNIQUE,
                  organization_id uuid NOT NULL REFERENCES compat_organizations(id));
                CREATE TEMP TABLE compat_resources(organization_id uuid NOT NULL REFERENCES compat_organizations(id),
                  external_key text NOT NULL,title text NOT NULL,PRIMARY KEY(organization_id,external_key));
                CREATE TEMP TABLE compat_assignments(organization_id uuid NOT NULL,user_id uuid NOT NULL REFERENCES compat_users(id),
                  external_key text NOT NULL,PRIMARY KEY(organization_id,user_id,external_key),
                  FOREIGN KEY(organization_id,external_key) REFERENCES compat_resources(organization_id,external_key));
            """)
            )
        yield conn
        if conn.in_transaction():
            conn.rollback()
        with conn.begin():
            for table in TABLES:
                conn.execute(text(f"DROP TABLE pg_temp.{table}"))


@pytest.mark.integration
def test_null_organization_metadata_has_bounded_safe_defaults(compatibility_conn):
    conn, organization_id = compatibility_conn, str(uuid4())
    with conn.begin():
        conn.execute(text("INSERT INTO compat_organizations(id) VALUES(:id)"), {"id": organization_id})
        result = compatibility.organization_metadata(conn, organization_id)
    assert result == {
        "id": organization_id,
        "name": "Untitled organization",
        "resource_keys": [],
        "locale": "en",
    }


@pytest.mark.integration
def test_absent_organization_is_not_found_without_mutating_existing_metadata(compatibility_conn):
    conn, existing_id, absent_id = compatibility_conn, str(uuid4()), str(uuid4())
    with conn.begin():
        conn.execute(
            text("INSERT INTO compat_organizations(id,name,resource_keys,locale) VALUES(:id,'Cedar','growth','pt')"),
            {"id": existing_id},
        )
        before = conn.execute(text("SELECT id,name,resource_keys,locale FROM compat_organizations")).all()
    with pytest.raises(AppError) as failure:
        with conn.begin():
            compatibility.organization_metadata(conn, absent_id)
    assert failure.value.status == 404
    assert failure.value.code == "organization_not_found"
    with conn.begin():
        assert conn.execute(text("SELECT id,name,resource_keys,locale FROM compat_organizations")).all() == before
        assert conn.execute(text("SELECT count(*) FROM compat_users")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM compat_assignments")).scalar_one() == 0


@pytest.mark.integration
def test_approval_rejection_precedes_any_organization_or_user_write(compatibility_conn):
    conn, existing_id, requested_id = compatibility_conn, str(uuid4()), str(uuid4())
    with conn.begin():
        conn.execute(
            text("INSERT INTO compat_organizations(id,name) VALUES(:id,'Original account')"),
            {"id": existing_id},
        )
        conn.execute(text("INSERT INTO compat_denied_addresses(email) VALUES('restricted@example.test')"))
    for organization_id in (existing_id, requested_id):
        with pytest.raises(AppError) as failure:
            with conn.begin():
                compatibility.approve_user(
                    conn, organization_id, "Changed account", " Restricted@Example.Test "
                )
        assert failure.value.code == "approval_denied"
    with conn.begin():
        assert (
            conn.execute(
                text("SELECT name FROM compat_organizations WHERE id=:id"), {"id": existing_id}
            ).scalar_one()
            == "Original account"
        )
        assert conn.execute(text("SELECT count(*) FROM compat_organizations")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM compat_users")).scalar_one() == 0


@pytest.mark.integration
def test_parameterized_search_is_literal_scoped_and_effective(compatibility_conn):
    conn, first, second = compatibility_conn, str(uuid4()), str(uuid4())
    with conn.begin():
        conn.execute(
            text("INSERT INTO compat_organizations(id) VALUES(:id)"), [{"id": first}, {"id": second}]
        )
        conn.execute(
            text("INSERT INTO compat_resources(organization_id,external_key,title) VALUES(:org,:key,:title)"),
            [
                {"org": first, "key": "growth", "title": "Growth 100%"},
                {"org": first, "key": "audience", "title": "Audience insights"},
                {"org": second, "key": "foreign", "title": "Growth 100%"},
            ],
        )
        assert [row["external_key"] for row in compatibility.search_resources(conn, first, "growth")] == [
            "growth"
        ]
        assert [row["external_key"] for row in compatibility.search_resources(conn, first, "%")] == ["growth"]
        assert compatibility.search_resources(conn, first, "' OR 1=1 --") == []


@pytest.mark.integration
def test_assignment_failure_preserves_old_rows_in_the_same_transaction(compatibility_conn):
    conn, organization_id, user_id = compatibility_conn, str(uuid4()), str(uuid4())
    with conn.begin():
        conn.execute(text("INSERT INTO compat_organizations(id) VALUES(:id)"), {"id": organization_id})
        conn.execute(
            text("INSERT INTO compat_users(id,email,organization_id) VALUES(:id,'viewer@example.test',:org)"),
            {"id": user_id, "org": organization_id},
        )
        conn.execute(
            text(
                "INSERT INTO compat_resources(organization_id,external_key,title) VALUES(:org,'original','Original resource')"
            ),
            {"org": organization_id},
        )
        compatibility.replace_assignments(conn, organization_id, user_id, ["original"])

    def fail():
        raise RuntimeError("Controlled write failure")

    with pytest.raises(RuntimeError):
        with conn.begin():
            compatibility.replace_assignments(conn, organization_id, user_id, [], after_delete=fail)
    with conn.begin():
        assert conn.execute(text("SELECT external_key FROM compat_assignments")).scalars().all() == [
            "original"
        ]

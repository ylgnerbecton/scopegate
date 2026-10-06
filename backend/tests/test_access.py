"""Real PostgreSQL integration tests, with isolated synthetic organizations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import access, catalog, entitlements, workspace


@pytest.fixture
def core_data(seed):
    ids = {
        key: str(uuid4())
        for key in (
            "org",
            "other_org",
            "project",
            "other_project",
            "manager_user",
            "viewer_user",
            "staff_user",
            "manager",
            "other_manager",
            "viewer",
            "other_viewer",
            "staff",
            "r1",
            "r2",
            "r3",
            "invite",
        )
    }
    with db.get_engine().begin() as conn:
        for key, name in (
            ("manager_user", "Morgan Reed"),
            ("viewer_user", "Casey Lane"),
            ("staff_user", "Jordan Vale"),
        ):
            conn.execute(
                text(
                    "INSERT INTO users(id,issuer,subject,email,display_name) VALUES(:id,'urn:core-test',:subject,:email,:name)"
                ),
                {"id": ids[key], "subject": ids[key], "email": f"{ids[key]}@example.test", "name": name},
            )
        for key in ("org", "other_org"):
            conn.execute(
                text("INSERT INTO organizations(id,name) VALUES(:id,'Sample workspace')"), {"id": ids[key]}
            )
        for project, organization in (("project", "org"), ("other_project", "other_org")):
            conn.execute(
                text("INSERT INTO projects(id,organization_id,name) VALUES(:id,:org,'Launch')"),
                {"id": ids[project], "org": ids[organization]},
            )
        for member, organization, user, role in (
            ("manager", "org", "manager_user", "access_manager"),
            ("viewer", "org", "viewer_user", "viewer"),
            ("other_manager", "other_org", "manager_user", "access_manager"),
            ("other_viewer", "other_org", "viewer_user", "viewer"),
        ):
            conn.execute(
                text("INSERT INTO memberships(id,organization_id,user_id,role) VALUES(:id,:org,:user,:role)"),
                {"id": ids[member], "org": ids[organization], "user": ids[user], "role": role},
            )
        conn.execute(
            text("""
            INSERT INTO memberships(id,organization_id,user_id,role,kind,expires_at,assignment_reason)
            VALUES(:id,:org,:user,'access_manager','staff',clock_timestamp()+interval '1 day','Support review')
        """),
            {"id": ids["staff"], "org": ids["org"], "user": ids["staff_user"]},
        )
        for resource, title in (("r1", "Growth 100%"), ("r2", "Audience_Insights"), ("r3", "Retention")):
            conn.execute(
                text("INSERT INTO resources(id,external_key,catalog_version) VALUES(:id,:external,1)"),
                {"id": ids[resource], "external": f"test-{ids[resource]}"},
            )
            conn.execute(
                text("INSERT INTO resource_localizations(resource_id,locale,title) VALUES(:id,'en',:title)"),
                {"id": ids[resource], "title": title},
            )
        for organization, project, resources, member in (
            ("org", "project", ("r1", "r2"), "viewer"),
            ("other_org", "other_project", ("r1", "r3"), "other_viewer"),
        ):
            for resource in resources:
                params = {
                    "org": ids[organization],
                    "project": ids[project],
                    "resource": ids[resource],
                    "member": ids[member],
                }
                conn.execute(
                    text(
                        "INSERT INTO project_resources(organization_id,project_id,resource_id) VALUES(:org,:project,:resource)"
                    ),
                    params,
                )
                conn.execute(
                    text(
                        "INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id) VALUES(:org,:member,:project,:resource)"
                    ),
                    params,
                )
        conn.execute(
            text("""
            INSERT INTO invitations(id,organization_id,recipient_email,token_hash,created_by,expires_at)
            VALUES(:id,:org,'invitee@example.test',:hash,:user,clock_timestamp()+interval '1 day')
        """),
            {
                "id": ids["invite"],
                "org": ids["org"],
                "hash": uuid4().hex + uuid4().hex,
                "user": ids["manager_user"],
            },
        )
        for resource in ("r1", "r2"):
            conn.execute(
                text(
                    "INSERT INTO invitation_resources(organization_id,invitation_id,project_id,resource_id) VALUES(:org,:invite,:project,:resource)"
                ),
                {
                    "org": ids["org"],
                    "invite": ids["invite"],
                    "project": ids["project"],
                    "resource": ids[resource],
                },
            )
    ids["actor"] = {"user_id": ids["manager_user"], "actor_key": f"user:{ids['manager_user']}"}
    ids["viewer_actor"] = {"user_id": ids["viewer_user"], "actor_key": f"user:{ids['viewer_user']}"}
    ids["platform"] = {"actor_key": "service:platform"}
    return ids


def grant_state(data, member="viewer", org="org", project="project", resource="r1"):
    with db.transaction() as conn:
        return db.row(
            conn,
            """
            SELECT g.state,m.access_version FROM resource_grants g JOIN memberships m
            ON m.organization_id=g.organization_id AND m.id=g.membership_id
            WHERE g.organization_id=:org AND g.membership_id=:member AND g.project_id=:project AND g.resource_id=:resource
        """,
            {"org": data[org], "member": data[member], "project": data[project], "resource": data[resource]},
        )


def apply(data, body=None, key=None, version=1, membership=None):
    return access.apply_diff(
        data["actor"],
        data["org"],
        membership or data["viewer"],
        data["project"],
        body or {"add": [], "remove": [data["r1"]], "reason": "Approved update"},
        key or str(uuid4()),
        version,
    )


@pytest.mark.integration
def test_scoped_delta_receipt_and_cross_account_preservation(core_data):
    data, key = core_data, str(uuid4())
    response = apply(data, key=key)
    assert response["access_version"] == 2
    assert grant_state(data)["state"] == "revoked"
    assert grant_state(data, "other_viewer", "other_org", "other_project")["state"] == "active"
    assert apply(data, key=key) == response
    with db.transaction() as conn:
        count = db.row(
            conn,
            "SELECT count(*) AS n FROM audit_events WHERE organization_id=:org AND action='grants.changed'",
            {"org": data["org"]},
        )
        receipt = db.row(
            conn,
            "SELECT * FROM command_receipts WHERE organization_id=:org AND idempotency_key=:key",
            {"org": data["org"], "key": key},
        )
    assert count["n"] == 1
    assert receipt["journal_reference"]


@pytest.mark.integration
def test_cross_account_target_is_concealed(core_data):
    with pytest.raises(AppError) as failure:
        apply(core_data, membership=core_data["other_viewer"])
    assert failure.value.status == 404
    assert grant_state(core_data, "other_viewer", "other_org", "other_project")["state"] == "active"


@pytest.mark.integration
def test_invalid_addition_rolls_back_the_valid_removal(core_data):
    with pytest.raises(AppError) as failure:
        apply(core_data, {"add": [core_data["r3"]], "remove": [core_data["r1"]], "reason": "Reviewed change"})
    assert failure.value.status == 404
    assert grant_state(core_data) == {"state": "active", "access_version": 1}


@pytest.mark.integration
def test_stale_version_and_noop_do_not_advance_twice(core_data):
    apply(core_data)
    with pytest.raises(AppError) as failure:
        apply(core_data)
    assert failure.value.status == 412
    response = apply(core_data, version=2)
    assert response["access_version"] == 2
    assert response["changed_grants"] == []


@pytest.mark.integration
def test_no_manager_role_or_staff_bypass(core_data):
    decision = access.own_decision(
        core_data["actor"],
        core_data["org"],
        {"project_id": core_data["project"], "resource_id": core_data["r1"]},
    )
    assert decision == {"allowed": False, "reason": "grant_missing"}
    with pytest.raises(AppError) as failure:
        access.create_report(
            core_data["actor"],
            core_data["org"],
            core_data["project"],
            {"name": "Review", "resource_ids": [core_data["r1"]]},
            str(uuid4()),
        )
    assert failure.value.status == 404


@pytest.mark.integration
def test_saved_report_reauthorizes_after_revocation(core_data):
    data = core_data
    report = access.create_report(
        data["viewer_actor"],
        data["org"],
        data["project"],
        {"name": "Weekly", "resource_ids": [data["r1"]]},
        str(uuid4()),
    )
    assert access.get_report(data["viewer_actor"], data["org"], data["project"], report["id"])[
        "resource_ids"
    ] == [data["r1"]]
    apply(data)
    with pytest.raises(AppError) as failure:
        access.get_report(data["viewer_actor"], data["org"], data["project"], report["id"])
    assert failure.value.status == 404


@pytest.mark.integration
def test_staff_never_satisfies_durable_manager_continuity(core_data):
    with pytest.raises(AppError) as failure:
        workspace.change_membership(
            core_data["actor"],
            core_data["org"],
            core_data["manager"],
            {"status": "suspended"},
            str(uuid4()),
            1,
        )
    assert failure.value.code == "last_manager_required"


@pytest.mark.integration
def test_grant_cursor_cannot_mix_new_version(core_data):
    data = core_data
    first = access.get_grants(data["actor"], data["org"], data["viewer"], data["project"], 1, None)
    assert first["next_cursor"]
    apply(data)
    with pytest.raises(AppError) as failure:
        access.get_grants(
            data["actor"], data["org"], data["viewer"], data["project"], 1, first["next_cursor"]
        )
    assert failure.value.status == 412


@pytest.mark.integration
def test_entitlement_disable_is_reviewed_atomic_and_reenable_restores_nothing(core_data):
    data = core_data
    impact = entitlements.get_impact(data["platform"], data["org"], data["project"], data["r1"], "disabled")
    assert impact["affected_memberships"] == impact["active_grants"] == impact["pending_invitations"] == 1
    body = {"status": "disabled", "impact_token": impact["impact_token"], "reason": "Contract scope changed"}
    key = str(uuid4())
    result = entitlements.set_entitlement(
        data["platform"], data["org"], data["project"], data["r1"], body, key, 1
    )
    assert result["entitlement_version"] == 2
    assert (
        entitlements.set_entitlement(data["platform"], data["org"], data["project"], data["r1"], body, key, 1)
        == result
    )
    impact = entitlements.get_impact(data["platform"], data["org"], data["project"], data["r1"], "active")
    entitlements.set_entitlement(
        data["platform"],
        data["org"],
        data["project"],
        data["r1"],
        {"status": "active", "impact_token": impact["impact_token"], "reason": "New contract"},
        str(uuid4()),
        2,
    )
    assert grant_state(data)["state"] == "revoked"
    with db.transaction() as conn:
        invitation = db.row(conn, "SELECT state FROM invitations WHERE id=:id", {"id": data["invite"]})
    assert invitation["state"] == "revoked"
    assert grant_state(data, resource="r2")["state"] == "active"


@pytest.mark.integration
def test_stale_impact_fails_without_side_effect(core_data):
    data = core_data
    impact = entitlements.get_impact(data["platform"], data["org"], data["project"], data["r1"], "disabled")
    apply(
        data,
        {"add": [data["r1"]], "remove": [], "reason": "Approved manager grant"},
        membership=data["manager"],
    )
    with pytest.raises(AppError) as failure:
        entitlements.set_entitlement(
            data["platform"],
            data["org"],
            data["project"],
            data["r1"],
            {"status": "disabled", "impact_token": impact["impact_token"], "reason": "Contract changed"},
            str(uuid4()),
            1,
        )
    assert failure.value.status == 412
    assert grant_state(data)["state"] == "active"


@pytest.mark.integration
def test_two_editors_cannot_both_commit_same_version(core_data):
    barrier = Barrier(2)

    def edit():
        barrier.wait(timeout=2)
        try:
            apply(core_data)
            return 200
        except AppError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: edit(), range(2)))
    assert sorted(results) == [200, 412]
    assert grant_state(core_data)["access_version"] == 2


@pytest.mark.integration
def test_literal_search_and_cursor_scope_binding(core_data):
    data = core_data
    percent = catalog.list_resources(
        data["viewer_actor"], data["org"], data["project"], "en", "%", "granted", 25, None
    )
    assert [item["id"] for item in percent["items"]] == [data["r1"]]
    first = catalog.list_resources(
        data["viewer_actor"], data["org"], data["project"], "en", "", "granted", 1, None
    )
    with pytest.raises(AppError) as failure:
        catalog.list_resources(
            data["viewer_actor"],
            data["other_org"],
            data["other_project"],
            "en",
            "",
            "granted",
            1,
            first["next_cursor"],
        )
    assert failure.value.status == 422


@pytest.mark.integration
def test_grant_add_receipt_after_later_revoke_cannot_restore_access(core_data):
    data = core_data
    body = {"add": [data["r1"]], "remove": [], "reason": "Explicit approved assignment"}
    key = str(uuid4())
    response = apply(data, body, key=key, membership=data["manager"])
    assert response["access_version"] == 2
    apply(data, membership=data["manager"], version=2)
    assert apply(data, body, key=key, membership=data["manager"]) == response
    assert grant_state(data, member="manager")["state"] == "revoked"
    assert grant_state(data, member="manager")["access_version"] == 3


@pytest.mark.integration
def test_entitlement_activation_receipt_after_archive_is_historical_only(core_data):
    data = core_data
    impact = entitlements.get_impact(data["platform"], data["org"], data["project"], data["r3"], "active")
    body = {"status": "active", "impact_token": impact["impact_token"], "reason": "New reviewed entitlement"}
    key = str(uuid4())
    response = entitlements.set_entitlement(
        data["platform"], data["org"], data["project"], data["r3"], body, key, 0
    )
    external = f"test-{data['r3']}"
    catalog.publish(
        {"actor_key": "service:catalog"},
        external,
        {
            "expected_version": 1,
            "version": 2,
            "status": "archived",
            "localizations": [{"locale": "en", "title": "Retired", "tags": []}],
        },
        str(uuid4()),
    )
    assert (
        entitlements.set_entitlement(data["platform"], data["org"], data["project"], data["r3"], body, key, 0)
        == response
    )
    with db.transaction() as conn:
        resource = db.row(conn, "SELECT status FROM resources WHERE id=:id", {"id": data["r3"]})
        grants = db.row(
            conn,
            "SELECT count(*) AS n FROM resource_grants WHERE organization_id=:org AND resource_id=:id",
            {"org": data["org"], "id": data["r3"]},
        )
    assert resource["status"] == "archived"
    assert grants["n"] == 0


@pytest.mark.integration
def test_duplicate_report_commands_share_one_receipt_and_output(core_data):
    data, barrier, key = core_data, Barrier(2), str(uuid4())
    body = {"name": "Shared command", "resource_ids": [data["r1"]]}

    def create():
        barrier.wait(timeout=2)
        return access.create_report(data["viewer_actor"], data["org"], data["project"], body, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(), range(2)))
    assert responses[0] == responses[1]
    with db.transaction() as conn:
        reports = db.row(
            conn, "SELECT count(*) AS n FROM report_configs WHERE organization_id=:org", {"org": data["org"]}
        )
    assert reports["n"] == 1


@pytest.mark.integration
def test_protected_use_rereads_policy_after_waiting_for_revocation(core_data, monkeypatch):
    data, waiting = core_data, Event()
    report = access.create_report(
        data["viewer_actor"],
        data["org"],
        data["project"],
        {"name": "Ordered admission", "resource_ids": [data["r1"]]},
        str(uuid4()),
    )
    original = db.lock_org

    def observed_lock(conn, organization_id, exclusive=True):
        if not exclusive:
            waiting.set()
        return original(conn, organization_id, exclusive)

    monkeypatch.setattr(db, "lock_org", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as conn:
            original(conn, data["org"], exclusive=True)
            future = pool.submit(
                access.get_report, data["viewer_actor"], data["org"], data["project"], report["id"]
            )
            assert waiting.wait(timeout=1)
            conn.execute(
                text(
                    "UPDATE resource_grants SET state='revoked' WHERE organization_id=:org AND membership_id=:member AND resource_id=:resource"
                ),
                {"org": data["org"], "member": data["viewer"], "resource": data["r1"]},
            )
        with pytest.raises(AppError) as failure:
            future.result(timeout=2)
    assert failure.value.status == 404


@pytest.mark.integration
def test_audit_insert_failure_rolls_back_grant_version_and_receipt(core_data, monkeypatch):
    data, key = core_data, str(uuid4())

    def rejected_audit(conn, *_args, **_kwargs):
        conn.execute(
            text("""
            INSERT INTO audit_events(actor_kind,actor_key,action,target_type,target_id,correlation_id)
            VALUES('invalid','test','invalid','test','test',gen_random_uuid())
        """)
        )

    monkeypatch.setattr(access, "audit", rejected_audit)
    with pytest.raises(IntegrityError):
        apply(data, key=key)
    assert grant_state(data) == {"state": "active", "access_version": 1}
    with db.transaction() as conn:
        receipts = db.row(
            conn,
            "SELECT count(*) AS n FROM command_receipts WHERE organization_id=:org AND idempotency_key=:key",
            {"org": data["org"], "key": key},
        )
    assert receipts["n"] == 0


@pytest.mark.integration
def test_two_durable_managers_cannot_suspend_themselves_concurrently(core_data):
    data, barrier = core_data, Barrier(2)
    with db.transaction() as conn:
        conn.execute(
            text("UPDATE memberships SET role='access_manager' WHERE id=:id"), {"id": data["viewer"]}
        )

    def suspend(pair):
        principal, membership_id = pair
        barrier.wait(timeout=2)
        try:
            workspace.change_membership(
                principal, data["org"], membership_id, {"status": "suspended"}, str(uuid4()), 1
            )
            return 200
        except AppError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(suspend, [(data["actor"], data["manager"]), (data["viewer_actor"], data["viewer"])])
        )
    assert sorted(outcomes) == [200, 409]
    with db.transaction() as conn:
        managers = db.row(
            conn,
            "SELECT count(*) AS n FROM memberships WHERE organization_id=:org AND role='access_manager' AND kind='customer' AND status='active'",
            {"org": data["org"]},
        )
    assert managers["n"] == 1


@pytest.mark.integration
def test_staff_expiry_is_checked_with_fresh_clock_after_lock_wait(core_data, monkeypatch):
    data, waiting = core_data, Event()
    original_lock, original_clock = db.lock_org, db.clock

    def observed_lock(conn, organization_id, exclusive=True):
        waiting.set()
        return original_lock(conn, organization_id, exclusive)

    def authoritative_clock(conn):
        if waiting.is_set():
            return conn.execute(text("SELECT clock_timestamp()+interval '2 days'")).scalar_one()
        return original_clock(conn)

    monkeypatch.setattr(db, "lock_org", observed_lock)
    monkeypatch.setattr(db, "clock", authoritative_clock)
    staff = {"user_id": data["staff_user"], "actor_key": f"user:{data['staff_user']}"}
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as conn:
            original_lock(conn, data["org"], exclusive=True)
            future = pool.submit(
                access.apply_diff,
                staff,
                data["org"],
                data["viewer"],
                data["project"],
                {"add": [], "remove": [data["r1"]], "reason": "Expired support assignment"},
                str(uuid4()),
                1,
            )
            assert waiting.wait(timeout=1)
        with pytest.raises(AppError) as failure:
            future.result(timeout=2)
    assert failure.value.status == 403
    assert grant_state(data)["state"] == "active"


@pytest.mark.integration
def test_destructive_entitlement_cap_rejects_without_changes(core_data):
    data = core_data
    people = [{"user": str(uuid4()), "member": str(uuid4())} for _ in range(201)]
    with db.get_engine().begin() as conn:
        conn.execute(
            text("INSERT INTO users(id,issuer,subject,email) VALUES(:user,'urn:cap-test',:subject,:email)"),
            [
                {**person, "subject": person["user"], "email": person["user"] + "@example.test"}
                for person in people
            ],
        )
        conn.execute(
            text("INSERT INTO memberships(id,user_id,organization_id) VALUES(:member,:user,:org)"),
            [{**person, "org": data["org"]} for person in people],
        )
        conn.execute(
            text(
                "INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id) VALUES(:org,:member,:project,:resource)"
            ),
            [
                {
                    "org": data["org"],
                    "member": person["member"],
                    "project": data["project"],
                    "resource": data["r1"],
                }
                for person in people
            ],
        )
    with pytest.raises(AppError) as failure:
        entitlements.set_entitlement(
            data["platform"],
            data["org"],
            data["project"],
            data["r1"],
            {"status": "disabled", "impact_token": "0" * 64, "reason": "Reviewed oversized transition"},
            str(uuid4()),
            1,
        )
    assert failure.value.code == "entitlement_impact_too_large"
    with db.transaction() as conn:
        count = db.row(
            conn,
            "SELECT count(*) AS n FROM resource_grants WHERE organization_id=:org AND resource_id=:resource AND state='active'",
            {"org": data["org"], "resource": data["r1"]},
        )
    assert count["n"] == 202


@pytest.mark.integration
def test_composite_membership_foreign_key_rejects_another_organization(core_data):
    data = core_data
    with pytest.raises(IntegrityError) as failure:
        with db.transaction() as conn:
            conn.execute(
                text(
                    "INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id) VALUES(:org,:member,:project,:resource)"
                ),
                {
                    "org": data["org"],
                    "member": data["other_viewer"],
                    "project": data["project"],
                    "resource": data["r1"],
                },
            )
    assert failure.value.orig.sqlstate == "23503"


@pytest.mark.integration
def test_first_manager_insert_failure_rolls_back_new_organization(core_data):
    data, organization_id = core_data, str(uuid4())

    def fail_membership_insert(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO memberships" in statement:
            raise RuntimeError("Controlled bootstrap failure")

    engine = db.get_engine()
    event.listen(engine, "before_cursor_execute", fail_membership_insert)
    try:
        with pytest.raises(RuntimeError):
            workspace.create_organization(
                data["platform"],
                {
                    "id": organization_id,
                    "name": "Bootstrap example",
                    "initial_manager_user_id": data["manager_user"],
                },
                str(uuid4()),
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_membership_insert)
    with db.transaction() as conn:
        organization = db.row(conn, "SELECT id FROM organizations WHERE id=:id", {"id": organization_id})
    assert organization is None


@pytest.mark.integration
def test_membership_search_is_literal_scoped_and_cursor_bound(core_data):
    data = core_data
    with db.transaction() as conn:
        conn.execute(
            text("UPDATE users SET display_name='Team_100%' WHERE id=:id"), {"id": data["manager_user"]}
        )
    result = workspace.list_memberships(data["actor"], data["org"], 25, None, "%")
    assert [item["id"] for item in result["items"]] == [data["manager"]]
    assert workspace.list_memberships(data["actor"], data["org"], 25, None, "' OR true --")["items"] == []
    first = workspace.list_memberships(data["actor"], data["org"], 1, None, "")
    with pytest.raises(AppError) as failure:
        workspace.list_memberships(data["actor"], data["org"], 1, first["next_cursor"], "Team")
    assert failure.value.status == 422


@pytest.mark.integration
def test_audit_filters_are_scoped_bounded_and_time_aware(core_data):
    data, now = core_data, datetime.now(UTC)
    apply(data)
    workspace.create_project(data["actor"], data["org"], {"name": "Audit filter sample"}, str(uuid4()))
    result = workspace.list_audit(
        data["actor"],
        data["org"],
        25,
        None,
        action="grants.changed",
        target_id=data["viewer"],
        from_time=now - timedelta(minutes=1),
        to_time=now + timedelta(minutes=1),
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["target_id"] == data["viewer"]
    assert (
        workspace.list_audit(data["actor"], data["org"], 25, None, target_id=data["other_viewer"])["items"]
        == []
    )
    for start, end in [(now, now - timedelta(days=1)), (now.replace(tzinfo=None), None)]:
        with pytest.raises(AppError) as failure:
            workspace.list_audit(data["actor"], data["org"], 25, None, from_time=start, to_time=end)
        assert failure.value.status == 422


@pytest.mark.integration
def test_audit_newest_first_keyset_handles_uuid_order_ties_and_intervening_insert(core_data):
    data = core_data
    action = "audit.pagination_probe"
    now = datetime(2026, 1, 3, tzinfo=UTC)
    newest = "00000000-0000-4000-8000-000000000001"
    tie_high = "00000000-0000-4000-8000-000000000007"
    tie_low = "00000000-0000-4000-8000-000000000003"
    oldest = "ffffffff-ffff-4fff-8fff-fffffffffff9"
    intervening = "00000000-0000-4000-8000-000000000002"

    def insert(identifier, timestamp, organization=None):
        with db.transaction() as conn:
            conn.execute(text("""
                INSERT INTO audit_events(id,organization_id,actor_kind,actor_user_id,actor_key,
                  action,target_type,target_id,safe_change_summary,correlation_id,created_at)
                VALUES(:id,:org,'user',:user,:actor,:action,'project',:target,'{}',:correlation,:created)
            """), {
                "id": identifier, "org": organization or data["org"], "user": data["manager_user"],
                "actor": data["actor"]["actor_key"], "action": action, "target": data["project"],
                "correlation": str(uuid4()), "created": timestamp,
            })

    for identifier, timestamp in [
        (oldest, now - timedelta(days=2)), (tie_low, now - timedelta(days=1)),
        (newest, now), (tie_high, now - timedelta(days=1)),
    ]:
        insert(identifier, timestamp)
    insert(str(uuid4()), now + timedelta(days=2), data["other_org"])
    first = workspace.list_audit(data["actor"], data["org"], 2, None, action=action)
    assert [item["id"] for item in first["items"]] == [newest, tie_high]
    assert first["next_cursor"]
    insert(intervening, now + timedelta(days=1))
    second = workspace.list_audit(data["actor"], data["org"], 2, first["next_cursor"], action=action)
    assert [item["id"] for item in second["items"]] == [tie_low, oldest]
    assert second["next_cursor"] is None
    assert len({item["id"] for item in first["items"] + second["items"]}) == 4
    refreshed = workspace.list_audit(data["actor"], data["org"], 2, None, action=action)
    assert [item["id"] for item in refreshed["items"]] == [intervening, newest]
    with pytest.raises(AppError) as failure:
        workspace.list_audit(data["actor"], data["org"], 2, first["next_cursor"], action="different.action")
    assert failure.value.status == 422


@pytest.mark.integration
def test_staff_explicit_grants_in_two_accounts_lose_only_the_selected_account(core_data):
    data, other_staff = core_data, str(uuid4())
    with db.transaction() as conn:
        conn.execute(
            text("""
            INSERT INTO memberships(id,organization_id,user_id,kind,expires_at,assignment_reason)
            VALUES(:id,:org,:user,'staff',clock_timestamp()+interval '1 day','Explicit scoped support')
        """),
            {"id": other_staff, "org": data["other_org"], "user": data["staff_user"]},
        )
        conn.execute(
            text("""
            INSERT INTO resource_grants(organization_id,membership_id,project_id,resource_id)
            VALUES(:org,:member,:project,:resource)
        """),
            [
                {
                    "org": data["org"],
                    "member": data["staff"],
                    "project": data["project"],
                    "resource": data["r1"],
                },
                {
                    "org": data["other_org"],
                    "member": other_staff,
                    "project": data["other_project"],
                    "resource": data["r1"],
                },
            ],
        )
    staff = {"user_id": data["staff_user"], "actor_key": f"user:{data['staff_user']}"}
    assert catalog.list_resources(staff, data["org"], data["project"], "en", "", "granted", 25, None)["items"]
    apply(data, membership=data["staff"])
    assert (
        catalog.list_resources(staff, data["org"], data["project"], "en", "", "granted", 25, None)["items"]
        == []
    )
    remaining = catalog.list_resources(
        staff, data["other_org"], data["other_project"], "en", "", "granted", 25, None
    )
    assert [resource["id"] for resource in remaining["items"]] == [data["r1"]]
    with db.transaction() as conn:
        membership = db.row(conn, "SELECT access_version FROM memberships WHERE id=:id", {"id": other_staff})
    assert membership["access_version"] == 1


@pytest.mark.integration
def test_absent_requested_locale_exposes_resolved_fallback(core_data):
    data = core_data
    result = catalog.list_resources(
        data["viewer_actor"], data["org"], data["project"], "fr", "Growth", "granted", 25, None
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["locale"] == "en"
    assert result["items"][0]["fallback_used"] is True
    assert result["items"][0]["title"] == "Growth 100%"


@pytest.mark.integration
def test_catalog_archive_waits_for_admitted_protected_output(core_data, monkeypatch):
    data, admitted, release, archive_waiting = core_data, Event(), Event(), Event()
    original = access.authorize_resources

    calls = 0

    def observed_authorization(*args, **kwargs):
        nonlocal calls
        original(*args, **kwargs)
        calls += 1
        if calls == 1:
            return  # Preliminary visibility is intentionally not a lock or admission.
        admitted.set()
        assert release.wait(timeout=1)

    def observe_archive(conn, cursor, statement, parameters, context, executemany):
        if "resources WHERE external_key" in statement and "FOR UPDATE" in statement:
            archive_waiting.set()

    monkeypatch.setattr(access, "authorize_resources", observed_authorization)
    engine = db.get_engine()
    event.listen(engine, "before_cursor_execute", observe_archive)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            output = pool.submit(
                access.create_report,
                data["viewer_actor"],
                data["org"],
                data["project"],
                {"name": "Bounded admitted output", "resource_ids": [data["r1"]]},
                str(uuid4()),
            )
            assert admitted.wait(timeout=1)
            publication = pool.submit(
                catalog.publish,
                {"actor_key": "service:catalog"},
                f"test-{data['r1']}",
                {
                    "expected_version": 1,
                    "version": 2,
                    "status": "archived",
                    "localizations": [{"locale": "en", "title": "Archived resource", "tags": []}],
                },
                str(uuid4()),
            )
            assert archive_waiting.wait(timeout=1)
            assert not publication.done()
            release.set()
            report = output.result(timeout=2)
            assert publication.result(timeout=2)["status"] == "archived"
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe_archive)
    with pytest.raises(AppError) as failure:
        access.get_report(data["viewer_actor"], data["org"], data["project"], report["id"])
    assert failure.value.code == "resource_unpublished"


@pytest.mark.integration
@pytest.mark.parametrize("operation", ["add", "remove"])
def test_known_foreign_and_unknown_grant_resources_are_concealed_equally(core_data, operation):
    data, results = core_data, []
    for resource_id in (data["r3"], str(uuid4())):
        body = {"add": [], "remove": [], "reason": "Unknown scoped resource"}
        body[operation] = [resource_id]
        with pytest.raises(AppError) as failure:
            apply(data, body)
        results.append((failure.value.status, failure.value.code))
    assert results == [(404, "resource_not_found"), (404, "resource_not_found")]
    assert grant_state(data) == {"state": "active", "access_version": 1}


@pytest.mark.integration
def test_foreign_org_preflight_conceals_known_and_unknown_resource_ids(core_data):
    data, results = core_data, []
    for resource_id in (data["r1"], str(uuid4())):
        with pytest.raises(AppError) as failure:
            access.apply_diff(
                data["viewer_actor"],
                str(uuid4()),
                data["viewer"],
                data["project"],
                {"add": [resource_id], "remove": [], "reason": "Foreign scope"},
                str(uuid4()),
                1,
            )
        results.append((failure.value.status, failure.value.code))
    assert results == [(404, "organization_not_found"), (404, "organization_not_found")]

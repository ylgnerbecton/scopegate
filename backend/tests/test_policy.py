import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scopegate.domain.policy import AccessContext, evaluate

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ALLOWED = AccessContext(True, True, None, True, True, True, True, NOW)


def test_complete_explicit_predicate_allows():
    assert evaluate(ALLOWED).allowed


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("organization_active", False, "organization_inactive"),
        ("membership_active", False, "membership_inactive"),
        ("membership_expires_at", NOW, "membership_expired"),
        ("membership_expires_at", NOW - timedelta(seconds=1), "membership_expired"),
        ("project_active", False, "project_inactive"),
        ("entitlement_active", False, "entitlement_inactive"),
        ("resource_published", False, "resource_unpublished"),
        ("grant_active", False, "grant_missing"),
    ],
)
def test_any_failed_condition_denies(field, value, reason):
    decision = evaluate(replace(ALLOWED, **{field: value}))
    assert decision.allowed is False
    assert decision.reason == reason


def test_future_expiration_is_allowed_until_actual_boundary():
    assert evaluate(replace(ALLOWED, membership_expires_at=NOW + timedelta(microseconds=1))).allowed


def test_first_denial_has_stable_precedence():
    decision = evaluate(replace(ALLOWED, membership_active=False, grant_active=False))
    assert decision.reason == "membership_inactive"


POLICY_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "specs/contracts/policy-cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("example", POLICY_CASES, ids=lambda example: example["id"])
def test_published_policy_examples(example):
    source = example["input"]
    context = AccessContext(
        organization_active=source["organization_active"],
        membership_active=source["membership_active"],
        membership_expires_at=None if source["membership_unexpired"] else NOW,
        project_active=source["project_active"],
        entitlement_active=source["entitlement_active"],
        resource_published=source["resource_published"],
        grant_active=source["explicit_grant"],
        now=NOW,
        authenticated=source["authenticated"],
        organization_matches=source["organization_matches"],
        project_matches=source["project_matches"],
    )
    decision = evaluate(context)
    assert {"allowed": decision.allowed, "reason": decision.reason} == example["expected"]

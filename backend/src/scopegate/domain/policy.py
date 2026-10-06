"""The same explicit predicate protects discovery and durable resource use."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccessContext:
    organization_active: bool
    membership_active: bool
    membership_expires_at: datetime | None
    project_active: bool
    entitlement_active: bool
    resource_published: bool
    grant_active: bool
    now: datetime
    authenticated: bool = True
    organization_matches: bool = True
    project_matches: bool = True


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def evaluate(context: AccessContext) -> Decision:
    """Roles and staff status deliberately do not bypass an explicit grant."""
    prerequisites = (
        (context.authenticated, "unauthenticated"),
        (context.organization_matches, "organization_mismatch"),
        (context.project_matches, "project_mismatch"),
        (context.organization_active, "organization_inactive"),
        (context.membership_active, "membership_inactive"),
    )
    for allowed, reason in prerequisites:
        if not allowed:
            return Decision(False, reason)
    if context.membership_expires_at and context.membership_expires_at <= context.now:
        return Decision(False, "membership_expired")
    checks = (
        (context.project_active, "project_inactive"),
        (context.entitlement_active, "entitlement_inactive"),
        (context.resource_published, "resource_unpublished"),
        (context.grant_active, "grant_missing"),
    )
    for allowed, reason in checks:
        if not allowed:
            return Decision(False, reason)
    return Decision(True, "allowed")

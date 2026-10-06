"""Workspace account boundaries and versioned membership management."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from scopegate.api.access import Key, Limit, Text, Version
from scopegate.dependencies import actor, platform_actor
from scopegate.services import workspace
from scopegate.services.common import expected_version

router = APIRouter(prefix="/api/v1", tags=["workspace"])
Cursor = Annotated[str | None, Query(max_length=2000)]


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: Text
    initial_manager_user_id: UUID


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text


class MembershipState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "suspended"]


@router.get("/organizations", operation_id="listOrganizations")
def organizations(
    principal: Annotated[dict, Depends(actor)], limit: Limit = 25, cursor: Cursor = None
) -> dict:
    return workspace.list_organizations(principal, limit, cursor)


@router.post("/platform/organizations", status_code=201, operation_id="createOrganization")
def create_organization(
    body: OrganizationCreate, principal: Annotated[dict, Depends(platform_actor)], idempotency_key: Key
) -> dict:
    return workspace.create_organization(principal, body.model_dump(mode="json"), idempotency_key)


@router.get("/organizations/{organization_id}", operation_id="getOrganization")
def organization(organization_id: UUID, principal: Annotated[dict, Depends(actor)]) -> dict:
    return workspace.get_organization(principal, str(organization_id))


@router.get("/organizations/{organization_id}/projects", operation_id="listProjects")
def projects(
    organization_id: UUID,
    principal: Annotated[dict, Depends(actor)],
    limit: Limit = 25,
    cursor: Cursor = None,
) -> dict:
    return workspace.list_projects(principal, str(organization_id), limit, cursor)


@router.post("/organizations/{organization_id}/projects", status_code=201, operation_id="createProject")
def create_project(
    organization_id: UUID,
    body: ProjectCreate,
    principal: Annotated[dict, Depends(actor)],
    idempotency_key: Key,
) -> dict:
    return workspace.create_project(
        principal, str(organization_id), body.model_dump(mode="json"), idempotency_key
    )


@router.get("/organizations/{organization_id}/memberships", operation_id="listMemberships")
def memberships(
    organization_id: UUID,
    principal: Annotated[dict, Depends(actor)],
    limit: Limit = 25,
    cursor: Cursor = None,
    q: Annotated[str, Query(max_length=200)] = "",
) -> dict:
    return workspace.list_memberships(principal, str(organization_id), limit, cursor, q)


@router.patch(
    "/organizations/{organization_id}/memberships/{membership_id}", operation_id="changeMembershipState"
)
def change_membership(
    organization_id: UUID,
    membership_id: UUID,
    body: MembershipState,
    principal: Annotated[dict, Depends(actor)],
    idempotency_key: Key,
    if_match: Version,
) -> dict:
    return workspace.change_membership(
        principal,
        str(organization_id),
        str(membership_id),
        body.model_dump(mode="json"),
        idempotency_key,
        expected_version(if_match),
    )


@router.get("/organizations/{organization_id}/audit-events", operation_id="listAuditEvents")
def audit_events(
    organization_id: UUID,
    principal: Annotated[dict, Depends(actor)],
    limit: Limit = 25,
    cursor: Cursor = None,
    action: Annotated[str | None, Query(max_length=200)] = None,
    target_type: Annotated[str | None, Query(max_length=100)] = None,
    target_id: Annotated[str | None, Query(max_length=200)] = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict:
    return workspace.list_audit(
        principal, str(organization_id), limit, cursor, action, target_type, target_id, from_time, to_time
    )

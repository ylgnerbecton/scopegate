"""Thin HTTP adapter for access transitions and current protected outputs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from scopegate.dependencies import actor
from scopegate.services import access
from scopegate.services.common import expected_version

router = APIRouter(prefix="/api/v1", tags=["access"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
Version = Annotated[str, Header(alias="If-Match", pattern='^"v[0-9]+"$')]
Limit = Annotated[int, Query(ge=1, le=100)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class GrantDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    add: list[UUID] = Field(max_length=100)
    remove: list[UUID] = Field(max_length=100)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class AccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    resource_id: UUID


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text
    resource_ids: list[UUID] = Field(min_length=1, max_length=100)


@router.get(
    "/organizations/{organization_id}/memberships/{membership_id}/projects/{project_id}/grants",
    operation_id="getGrants",
)
def get_grants(
    organization_id: UUID,
    membership_id: UUID,
    project_id: UUID,
    principal: Annotated[dict, Depends(actor)],
    limit: Limit = 25,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> dict:
    return access.get_grants(
        principal, str(organization_id), str(membership_id), str(project_id), limit, cursor
    )


@router.patch(
    "/organizations/{organization_id}/memberships/{membership_id}/projects/{project_id}/grants",
    operation_id="applyGrantDiff",
)
def apply_grants(
    organization_id: UUID,
    membership_id: UUID,
    project_id: UUID,
    body: GrantDiff,
    principal: Annotated[dict, Depends(actor)],
    idempotency_key: Key,
    if_match: Version,
) -> dict:
    return access.apply_diff(
        principal,
        str(organization_id),
        str(membership_id),
        str(project_id),
        body.model_dump(mode="json"),
        idempotency_key,
        expected_version(if_match),
    )


@router.post("/organizations/{organization_id}/access-decisions", operation_id="evaluateOwnAccess")
def own_decision(
    organization_id: UUID, body: AccessRequest, principal: Annotated[dict, Depends(actor)]
) -> dict:
    return access.own_decision(principal, str(organization_id), body.model_dump(mode="json"))


@router.post(
    "/organizations/{organization_id}/projects/{project_id}/report-configs",
    status_code=201,
    operation_id="createReportConfig",
)
def create_report(
    organization_id: UUID,
    project_id: UUID,
    body: ReportCreate,
    principal: Annotated[dict, Depends(actor)],
    idempotency_key: Key,
) -> dict:
    payload = body.model_dump(mode="json")
    if len(set(payload["resource_ids"])) != len(payload["resource_ids"]):
        from scopegate.errors import AppError

        raise AppError(422, "validation_error", "Report resources must be unique.")
    return access.create_report(principal, str(organization_id), str(project_id), payload, idempotency_key)


@router.get(
    "/organizations/{organization_id}/projects/{project_id}/report-configs/{report_config_id}",
    operation_id="getReportConfig",
)
def get_report(
    organization_id: UUID,
    project_id: UUID,
    report_config_id: UUID,
    principal: Annotated[dict, Depends(actor)],
) -> dict:
    return access.get_report(principal, str(organization_id), str(project_id), str(report_config_id))

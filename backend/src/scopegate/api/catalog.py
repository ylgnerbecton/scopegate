"""Tenant search and explicitly separated publisher/platform credentials."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

from scopegate.api.access import Key, Limit, Version
from scopegate.dependencies import actor, catalog_actor, platform_actor
from scopegate.services import catalog, entitlements
from scopegate.services.common import expected_version

router = APIRouter(prefix="/api/v1", tags=["catalog"])
Locale = Literal["en", "pt", "es", "fr"]


class Localization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Locale
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    description: str | None = Field(default=None, max_length=10000)
    tags: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(max_length=30)


class CatalogPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    version: int = Field(ge=1)
    status: Literal["published", "archived"]
    avatar_url: HttpUrl | None = None
    localizations: list[Localization] = Field(min_length=1, max_length=4)


class EntitlementState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "disabled"]
    impact_token: str = Field(pattern="^[a-f0-9]{64}$")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


@router.get(
    "/organizations/{organization_id}/projects/{project_id}/resources", operation_id="listProjectResources"
)
def resources(
    organization_id: UUID,
    project_id: UUID,
    principal: Annotated[dict, Depends(actor)],
    locale: Locale = "en",
    q: Annotated[str, Query(max_length=200)] = "",
    view: Literal["granted", "entitled"] = "granted",
    limit: Limit = 25,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> dict:
    return catalog.list_resources(
        principal, str(organization_id), str(project_id), locale, q, view, limit, cursor
    )


@router.put("/catalog/resources/{external_key}", operation_id="publishResource")
def publish_resource(
    external_key: Annotated[str, Path(min_length=1, max_length=128)],
    body: CatalogPublish,
    principal: Annotated[dict, Depends(catalog_actor)],
    idempotency_key: Key,
) -> dict:
    return catalog.publish(
        principal, external_key, body.model_dump(mode="json", exclude_unset=True), idempotency_key
    )


@router.get(
    "/organizations/{organization_id}/projects/{project_id}/entitlements/{resource_id}/impact",
    operation_id="getEntitlementImpact",
)
def entitlement_impact(
    organization_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    desired_status: Literal["active", "disabled"],
    principal: Annotated[dict, Depends(platform_actor)],
) -> dict:
    return entitlements.get_impact(
        principal, str(organization_id), str(project_id), str(resource_id), desired_status
    )


@router.put(
    "/organizations/{organization_id}/projects/{project_id}/entitlements/{resource_id}",
    operation_id="setEntitlement",
)
def set_entitlement(
    organization_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    body: EntitlementState,
    principal: Annotated[dict, Depends(platform_actor)],
    idempotency_key: Key,
    if_match: Version,
) -> dict:
    return entitlements.set_entitlement(
        principal,
        str(organization_id),
        str(project_id),
        str(resource_id),
        body.model_dump(mode="json"),
        idempotency_key,
        expected_version(if_match),
    )

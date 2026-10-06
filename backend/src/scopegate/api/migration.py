"""Scoped reviewer workbench. Authority switches are deliberately absent."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from scopegate.api.invitations import mutation_actor
from scopegate.services import identity, migration
from scopegate.services.common import expected_version

router = APIRouter(prefix="/api/v1/organizations/{organization_id}/migration-runs", tags=["migration"])


class LedgerResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["mapped", "review_required", "approved_change", "retained", "rejected"]
    target_kind: str | None = Field(default=None, max_length=100)
    target_id: str | None = Field(default=None, max_length=200)
    decision_reason: str = Field(min_length=3, max_length=1000)
    assigned_owner_user_id: UUID | None = None


@router.get("", operation_id="listMigrationRuns")
def runs(
    *,
    organization_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = None,
    actor: Annotated[dict, Depends(identity.get_principal)],
):
    return migration.list_runs(actor, str(organization_id), limit, cursor)


@router.get("/{run_id}/items", operation_id="listMigrationLedger")
def items(
    *,
    organization_id: UUID,
    run_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = None,
    actor: Annotated[dict, Depends(identity.get_principal)],
):
    return migration.list_items(actor, str(organization_id), str(run_id), limit, cursor)


@router.patch("/{run_id}/items/{ledger_id}", operation_id="resolveMigrationLedger")
def resolve(
    *,
    organization_id: UUID,
    run_id: UUID,
    ledger_id: UUID,
    body: LedgerResolution,
    version: str = Header(alias="If-Match"),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    actor: Annotated[dict, Depends(mutation_actor)],
):
    return migration.resolve(
        actor,
        str(organization_id),
        str(run_id),
        str(ledger_id),
        body.model_dump(mode="json"),
        expected_version(version),
        key,
    )


@router.get("/{run_id}/manifest", operation_id="exportMigrationManifest")
def manifest(
    *,
    organization_id: UUID,
    run_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = None,
    actor: Annotated[dict, Depends(identity.get_principal)],
):
    return migration.export_manifest(actor, str(organization_id), str(run_id), limit, cursor)

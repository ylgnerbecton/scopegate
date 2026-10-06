"""Invitation HTTP validation and protected local delivery evidence."""

from typing import Annotated
from uuid import UUID

from email_validator import validate_email
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from scopegate.config import get_settings
from scopegate.services import delivery, enrollment, identity

router = APIRouter(prefix="/api/v1", tags=["enrollment"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    resource_id: UUID


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip()
        validate_email(
            value,
            check_deliverability=False,
            test_environment=get_settings().environment in {"local", "test"},
        )
        return value

    expires_in_hours: int = Field(default=72, ge=1, le=168)
    resources: list[Selection] = Field(min_length=1, max_length=100)


class InvitationToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=43, max_length=256)


class DeliveryReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=8, max_length=500)


def mutation_actor(
    *,
    request: Request,
    principal: Annotated[dict, Depends(identity.get_principal)],
    csrf_header: Annotated[str, Header(alias="X-CSRF-Token", min_length=32)],
) -> dict:
    identity.require_csrf(request, principal)
    return principal


@router.get("/organizations/{organization_id}/invitations", operation_id="listInvitations")
def list_invitations(
    *,
    organization_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = None,
    actor: Annotated[dict, Depends(identity.get_principal)],
):
    return enrollment.list_invitations(actor, str(organization_id), limit, cursor)


@router.post("/organizations/{organization_id}/invitations", status_code=201, operation_id="createInvitation")
def create_invitation(
    *,
    organization_id: UUID,
    body: InvitationCreate,
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    actor: Annotated[dict, Depends(mutation_actor)],
):
    return enrollment.create_invitation(actor, str(organization_id), body.model_dump(mode="json"), key)


@router.post(
    "/organizations/{organization_id}/invitations/{invitation_id}/resend",
    status_code=201,
    operation_id="resendInvitation",
)
def resend_invitation(
    *,
    organization_id: UUID,
    invitation_id: UUID,
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    actor: Annotated[dict, Depends(mutation_actor)],
):
    return enrollment.change_invitation(actor, str(organization_id), str(invitation_id), key, "resend")


@router.post(
    "/organizations/{organization_id}/invitations/{invitation_id}/revoke", operation_id="revokeInvitation"
)
def revoke_invitation(
    *,
    organization_id: UUID,
    invitation_id: UUID,
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    actor: Annotated[dict, Depends(mutation_actor)],
):
    return enrollment.change_invitation(actor, str(organization_id), str(invitation_id), key, "revoke")


@router.post("/invitations/preview", operation_id="previewInvitation")
def preview_invitation(*, body: InvitationToken, actor: Annotated[dict, Depends(mutation_actor)]):
    return enrollment.preview(actor, body.token)


@router.post("/invitations/accept", operation_id="acceptInvitation")
def accept_invitation(
    *,
    body: InvitationToken,
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    actor: Annotated[dict, Depends(mutation_actor)],
):
    return enrollment.accept(actor, body.token, key)


@router.get("/organizations/{organization_id}/mailbox", operation_id="listLocalMailbox")
def local_mailbox(*, organization_id: UUID, actor: Annotated[dict, Depends(identity.get_principal)]):
    return delivery.mailbox(actor, str(organization_id))


@router.post(
    "/organizations/{organization_id}/outbox/{message_id}/replay", operation_id="replayOutboxMessage"
)
def replay_delivery(
    *,
    organization_id: UUID,
    message_id: UUID,
    body: DeliveryReplay,
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    actor: Annotated[dict, Depends(mutation_actor)],
):
    return delivery.replay(actor, str(organization_id), str(message_id), body.reason, key)

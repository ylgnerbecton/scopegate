"""Independent local fixtures that illustrate recipient and delivery states."""

import secrets

from sqlalchemy import text

from scopegate.config import get_settings
from scopegate.seed import ORGS, PROJECTS, RESOURCES, USERS, identifier
from scopegate.services.delivery import enqueue
from scopegate.services.identity import token_hash


def seed_demo_states(conn) -> None:
    if get_settings().environment != "local":
        return
    for index, email, expired in [
        (1, "expired@example.test", True),
        (2, "failed@example.test", False),
    ]:
        invitation_id = identifier(6, index)
        if conn.execute(text("SELECT 1 FROM invitations WHERE id=:id"), {"id": invitation_id}).scalar():
            continue
        token = secrets.token_urlsafe(32)
        conn.execute(
            text("""INSERT INTO invitations(id,organization_id,recipient_email,token_hash,
              created_by,created_at,expires_at) VALUES(:id,:org,:email,:hash,:user,
              clock_timestamp()-interval '2 hours',
              CASE WHEN :expired THEN clock_timestamp()-interval '1 hour'
                ELSE clock_timestamp()+interval '72 hours' END)"""),
            {"id": invitation_id, "org": ORGS["cedar"], "email": email,
             "hash": token_hash(token), "user": USERS["manager-cedar"], "expired": expired},
        )
        conn.execute(
            text("""INSERT INTO invitation_resources(organization_id,invitation_id,project_id,resource_id)
              VALUES(:org,:invite,:project,:resource)"""),
            {"org": ORGS["cedar"], "invite": invitation_id,
             "project": PROJECTS["harbor"], "resource": RESOURCES["growth-signals"]},
        )
        message = enqueue(conn, ORGS["cedar"], invitation_id, email, token)
        conn.execute(
            text("""UPDATE outbox_messages SET state='failed',failed_at=clock_timestamp(),
              attempts=8,generation_attempts=8,last_error_code=:error WHERE id=:id"""),
            {"id": message, "error": "invitation_unavailable" if expired else "retry_budget_exhausted"},
        )

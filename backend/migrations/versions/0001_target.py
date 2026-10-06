"""Fresh target schema. Never runs against a legacy database."""

from pathlib import Path

from alembic import op

revision = "0001_target"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "specs/contracts/schema.sql").read_text()
    statements = source.replace("BEGIN;", "").replace("COMMIT;", "")
    op.get_bind().exec_driver_sql(statements)


def downgrade() -> None:
    raise RuntimeError("Destructive schema rollback is outside the supported recovery procedure.")

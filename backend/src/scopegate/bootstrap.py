"""Local bootstrap: migrate, grant least privilege, seed independent examples."""

import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scopegate.config import get_settings
from scopegate.demo_states import seed_demo_states
from scopegate.seed import seed


def bootstrap() -> None:
    settings = get_settings()
    if settings.environment not in {"local", "test"}:
        raise RuntimeError("The synthetic bootstrap is local only.")
    settings.journal_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.mailbox_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine(settings.migration_database_url)
    password = make_url(settings.database_url).password
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='scopegate_app'")).scalar()
        # Values pass through PostgreSQL quoting, never through shell text.
        quoted = conn.execute(text("SELECT quote_literal(:value)"), {"value": password}).scalar()
        verb = "ALTER" if exists else "CREATE"
        conn.exec_driver_sql(
            f"{verb} ROLE scopegate_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {quoted}"
        )
        conn.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    root = Path(__file__).resolve().parents[3]
    executable = os.environ.get("SCOPEGATE_ALEMBIC_EXECUTABLE", str(root / "backend/.venv/bin/alembic"))
    subprocess.run([executable, "-c", str(root / "backend/alembic.ini"), "upgrade", "head"], check=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("GRANT USAGE ON SCHEMA public TO scopegate_app")
        conn.exec_driver_sql(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO scopegate_app"
        )
        conn.exec_driver_sql("REVOKE UPDATE,DELETE,TRUNCATE ON audit_events FROM scopegate_app")
        conn.exec_driver_sql("REVOKE ALL ON alembic_version FROM scopegate_app")
        conn.exec_driver_sql("GRANT SELECT ON alembic_version TO scopegate_app")
        conn.exec_driver_sql("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO scopegate_app")
        seed(conn)
        seed_demo_states(conn)
    engine.dispose()
    print("Scopegate schema and synthetic workspace are ready.")


if __name__ == "__main__":
    bootstrap()

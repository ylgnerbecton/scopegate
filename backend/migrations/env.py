"""DDL uses a dedicated credential; the runtime role never owns tables."""

from alembic import context
from sqlalchemy import create_engine, pool

from scopegate.config import get_settings

config = context.config


def run() -> None:
    engine = create_engine(get_settings().migration_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()

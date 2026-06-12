"""Alembic migrations environment for weebot.

Weebot uses raw SQL (not SQLAlchemy ORM), so migrations are written manually.
This env.py configures Alembic to connect to the weebot sessions database
using the path from weebot's own settings (or env var).
"""
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from weebot settings if available
try:
    from weebot.config.settings import SESSIONS_DB
    db_path = Path(SESSIONS_DB).resolve()
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
except ImportError:
    pass  # Fall back to alembic.ini value

# Weebot doesn't use SQLAlchemy models, so autogenerate is not supported.
# Set target_metadata to None and write migrations manually.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to live DB)."""
    from sqlalchemy import create_engine
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite requires transactional DDL
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

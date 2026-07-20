from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import suppress
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
ALEMBIC_BASELINE_REVISION = "ee341f3c76b7"
INSTANCE_DIR.mkdir(exist_ok=True)
with suppress(OSError):
    INSTANCE_DIR.chmod(0o700)


def database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if not configured:
        return f"sqlite:///{(INSTANCE_DIR / 'grindtracker.db').as_posix()}"
    if configured.startswith("postgresql://"):
        return configured.replace("postgresql://", "postgresql+psycopg://", 1)
    if configured.startswith("postgres://"):
        return configured.replace("postgres://", "postgresql+psycopg://", 1)
    if configured.startswith("sqlite:///"):
        if configured == "sqlite:///:memory:":
            return configured
        value = configured.removeprefix("sqlite:///")
        path = Path(value)
        if not path.is_absolute():
            return f"sqlite:///{(INSTANCE_DIR / path).as_posix()}"
    return configured


DATABASE_URL = database_url()
is_memory_database = DATABASE_URL == "sqlite:///:memory:"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15} if DATABASE_URL.startswith("sqlite") else {},
    poolclass=StaticPool if is_memory_database else None,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        """Make SQLite honor the foreign keys declared by the ORM models."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()


def init_db() -> None:
    tables = set(inspect(engine).get_table_names())
    config = Config(str(BASE_DIR / "alembic.ini"))
    if not tables:
        command.upgrade(config, "head")
    elif "alembic_version" not in tables:
        Base.metadata.create_all(engine)
        _migrate_legacy_sqlite()
        command.stamp(config, ALEMBIC_BASELINE_REVISION)
        command.upgrade(config, "head")
    else:
        command.upgrade(config, "head")
    if engine.dialect.name == "sqlite" and engine.url.database and engine.url.database != ":memory:":
        with suppress(OSError):
            Path(engine.url.database).chmod(0o600)


def assert_database_current() -> None:
    """Fail fast when production starts before its one-off migration step."""
    config = Config(str(BASE_DIR / "alembic.ini"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    if current != expected:
        current_label = ", ".join(sorted(current)) or "unversioned"
        expected_label = ", ".join(sorted(expected)) or "no migration head"
        raise RuntimeError(
            "Database schema is not current "
            f"(database: {current_label}; expected: {expected_label}). "
            "Run `python cli.py init-db` once before starting API workers."
        )


def _migrate_legacy_sqlite() -> None:
    """Bridge catalog columns before stamping a pre-Alembic SQLite database.

    New installations and all later changes use migrations.
    """
    if engine.dialect.name != "sqlite" or "vehicles" not in inspect(engine).get_table_names():
        return
    columns = {column["name"] for column in inspect(engine).get_columns("vehicles")}
    additions = {
        "source_key": "VARCHAR(160)",
        "source_name": "VARCHAR(80)",
        "source_version": "VARCHAR(64)",
        "folder_key": "VARCHAR(160)",
        "role": "VARCHAR(64)",
        "availability": "VARCHAR(32) DEFAULT 'researchable'",
        "research_type": "VARCHAR(32) DEFAULT 'standard'",
        "tree_column": "INTEGER",
        "tree_order": "INTEGER",
        "rp_multiplier": "FLOAT",
        "sl_cost": "INTEGER",
        "retired_at": "DATETIME",
    }
    with engine.begin() as connection:
        for name, sql_type in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE vehicles ADD COLUMN {name} {sql_type}"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_vehicles_source_key ON vehicles (source_key)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_vehicles_source_name ON vehicles (source_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_vehicles_source_version ON vehicles (source_version)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_vehicles_folder_key ON vehicles (folder_key)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_vehicles_role ON vehicles (role)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_vehicles_availability ON vehicles (availability)"))


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session

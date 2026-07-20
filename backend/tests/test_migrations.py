from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import database as database_module
from models import Base

BACKEND = Path(__file__).resolve().parents[1]


def test_postgresql_urls_select_the_installed_psycopg_driver(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://pilot:secret@db.example/grindtracker")
    assert database_module.database_url() == "postgresql+psycopg://pilot:secret@db.example/grindtracker"

    monkeypatch.setenv("DATABASE_URL", "postgres://pilot:secret@db.example/grindtracker")
    assert database_module.database_url() == "postgresql+psycopg://pilot:secret@db.example/grindtracker"

    explicit = "postgresql+psycopg://pilot:secret@db.example/grindtracker"
    monkeypatch.setenv("DATABASE_URL", explicit)
    assert database_module.database_url() == explicit


def head_revision() -> str:
    configuration = Config(str(BACKEND / "alembic.ini"))
    configuration.set_main_option("script_location", str(BACKEND / "migrations"))
    revision = ScriptDirectory.from_config(configuration).get_current_head()
    assert revision is not None
    return revision


def database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def run_backend(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url(database)
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    return result


def assert_current_schema(database: Path) -> None:
    isolated_engine = create_engine(database_url(database))
    try:
        schema = inspect(isolated_engine)
        tables = set(schema.get_table_names())
        assert "alembic_version" in tables
        assert "user_profiles" not in tables
        assert "valid_from" not in {column["name"] for column in schema.get_columns("vehicles")}
        with isolated_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head_revision()
    finally:
        isolated_engine.dispose()


def test_empty_database_upgrades_to_head_without_schema_drift(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"

    run_backend(database, "-m", "alembic", "upgrade", "head")
    check = run_backend(database, "-m", "alembic", "check")

    assert "No new upgrade operations detected" in check.stdout
    assert_current_schema(database)


def test_pre_alembic_database_runs_cleanup_migrations_after_adoption(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    legacy_engine = create_engine(database_url(database))
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE user_profiles (
                    user_id INTEGER PRIMARY KEY REFERENCES users (id),
                    avg_rp_per_battle INTEGER,
                    avg_battle_minutes INTEGER,
                    has_premium BOOLEAN NOT NULL DEFAULT 0,
                    booster_percent INTEGER,
                    skill_bonus_percent INTEGER
                )
                """
            )
        )
        connection.execute(text("ALTER TABLE vehicles ADD COLUMN valid_from DATETIME"))
    legacy_engine.dispose()

    run_backend(database, "cli.py", "init-db")
    run_backend(database, "-m", "alembic", "check")

    assert_current_schema(database)

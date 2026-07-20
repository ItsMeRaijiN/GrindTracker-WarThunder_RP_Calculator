from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-that-is-at-least-32-bytes-long"

from app import app  # noqa: E402
from database import SessionLocal, engine  # noqa: E402
from datamine import build_normalized_snapshot  # noqa: E402
from importer import import_from_json_dict  # noqa: E402
from models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        data = build_normalized_snapshot(BACKEND / "tests" / "fixtures" / "datamine", minimum_vehicles=1)
        import_from_json_dict(session, data)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as value:
        yield value

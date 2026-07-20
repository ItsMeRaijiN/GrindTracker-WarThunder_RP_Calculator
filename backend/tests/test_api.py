from __future__ import annotations

import asyncio
import ipaddress
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

import security
from app import app
from calc import rank_efficiency
from database import SessionLocal, engine
from datamine import build_normalized_snapshot
from importer import import_from_json_dict
from models import (
    AuthThrottle,
    CatalogSnapshot,
    User,
    UserSession,
    UserVehicleProgress,
    Vehicle,
    VehicleClass,
    VehicleEdge,
    utc_now,
)
from security import SESSION_COOKIE_NAME, client_ip

FIXTURE = Path(__file__).parent / "fixtures" / "datamine"


def tree_nodes(client) -> list[dict]:
    response = client.get("/api/tree", params={"nation": "usa", "class": "army"})
    assert response.status_code == 200
    return response.json()["nodes"]


@pytest.mark.parametrize(
    ("target_rank", "expected"),
    [(1, 0.9), (2, 1.0), (3, 1.0), (4, 0.4)],
)
def test_regular_vehicle_rank_research_efficiency(target_rank, expected):
    research_vehicle = Vehicle(rank_id=2, is_premium=False)
    target = Vehicle(rank_id=target_rank)

    assert rank_efficiency(research_vehicle, target) == expected


def test_catalog_and_tree(client):
    nations = client.get("/api/nations")
    assert nations.status_code == 200
    assert any(item["slug"] == "usa" for item in nations.json())

    tree = client.get("/api/tree", params={"nation": "usa", "class": "army"})
    assert tree.status_code == 200
    body = tree.json()
    assert body["meta"]["vehicle_count"] >= 1
    assert body["meta"]["research_column_count"] == 1
    assert body["meta"]["research_efficiency"]["target_above"]["2"] == 0.4
    assert all(item["nation"] == "usa" for item in body["nodes"])
    reserve = next(item for item in body["nodes"] if item["name"] == "M2A4")
    assert reserve["rp_cost"] is None
    assert reserve["is_reserve"] is True
    assert all(item["is_reserve"] is False for item in body["nodes"] if item["rp_cost"])
    assert all(item["is_reserve"] is False for item in body["nodes"] if item["type"] != "tree")


def test_database_is_alembic_versioned(client):
    inspector = inspect(engine)
    assert inspector is not None
    # noinspection PyUnresolvedReferences
    assert "alembic_version" in inspector.get_table_names()


def test_observed_rp_is_not_multiplied_again(client):
    vehicles = tree_nodes(client)
    vehicle = next(item for item in vehicles if item["rp_cost"])
    response = client.post(
        "/api/calc/estimate",
        json={
            "vehicle_id": vehicle["id"],
            "recent_battles": [{"rp": 1000, "minutes": 10}],
            "has_premium": True,
            "booster_percent": 100,
            "rp_is_base": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["effective_rp_per_battle"] == 1000


def test_base_rp_uses_additive_economy_bonuses(client):
    vehicles = tree_nodes(client)
    vehicle = next(item for item in vehicles if item["rp_cost"])
    response = client.post(
        "/api/calc/estimate",
        json={
            "vehicle_id": vehicle["id"],
            "avg_rp_per_battle": 1000,
            "has_premium": True,
            "booster_percent": 50,
            "skill_bonus_percent": 20,
            "rp_is_base": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["effective_rp_per_battle"] == 2700


def test_research_vehicle_multiplier_and_direct_predecessor_bonus(client):
    vehicles = tree_nodes(client)
    by_name = {vehicle["name"]: vehicle for vehicle in vehicles}
    response = client.post(
        "/api/calc/estimate",
        json={
            "vehicle_id": by_name["M3A1 Stuart"]["id"],
            "research_vehicle_id": by_name["M3 Stuart"]["id"],
            "avg_rp_per_battle": 1000,
            "rp_is_base": True,
            "has_premium": True,
            "has_talisman": True,
            "game_mode": "rb",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effective_rp_per_battle"] == 4125
    assert body["modifiers"]["vehicle_rp_multiplier"] == 1.25
    assert body["modifiers"]["research_efficiency"] == 1.1
    assert body["modifiers"]["direct_predecessor_bonus"] is True


def test_observed_rp_only_adds_target_efficiency(client):
    vehicles = tree_nodes(client)
    by_name = {vehicle["name"]: vehicle for vehicle in vehicles}
    response = client.post(
        "/api/calc/estimate",
        json={
            "vehicle_id": by_name["M901 ITV"]["id"],
            "research_vehicle_id": by_name["M2A4"]["id"],
            "avg_rp_per_battle": 1000,
            "rp_is_base": False,
            "has_premium": True,
            "booster_percent": 100,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effective_rp_per_battle"] == 200
    assert body["modifiers"]["vehicle_rp_multiplier_applied"] is False
    assert body["modifiers"]["research_efficiency"] == 0.2


def test_auth_and_remote_progress(client):
    registration = client.post("/api/auth/register", json={"email": "pilot@example.com", "password": "correct-horse"})
    assert registration.status_code == 201
    assert "token" not in registration.json()
    assert "HttpOnly" in registration.headers["set-cookie"]
    assert "SameSite=lax" in registration.headers["set-cookie"]
    csrf = registration.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    vehicle = next(item for item in tree_nodes(client) if item["rp_cost"])

    saved = client.put(
        "/api/progress",
        json={"progress": {str(vehicle["id"]): {"rp_earned": 123, "done": False}}},
        headers=headers,
    )
    assert saved.status_code == 200
    progress = client.get("/api/progress")
    assert progress.status_code == 200
    assert progress.json()[0]["rp_earned"] == min(123, vehicle["rp_cost"])


def test_bulk_progress_sync_can_reduce_existing_values(client):
    registration = client.post(
        "/api/auth/register",
        json={"email": "bulk@example.com", "password": "long-correct-horse"},
    )
    headers = {"X-CSRF-Token": registration.json()["csrf_token"]}
    vehicles = [item for item in tree_nodes(client) if item["rp_cost"]]
    first, second = vehicles[:2]
    initial = client.put(
        "/api/progress",
        headers=headers,
        json={
            "progress": {
                str(first["id"]): {"rp_earned": first["rp_cost"], "done": True},
                str(second["id"]): {"rp_earned": 321, "done": False},
            }
        },
    )
    assert initial.status_code == 200

    reduced = client.put(
        "/api/progress",
        headers=headers,
        json={"progress": {str(first["id"]): {"rp_earned": 10, "done": False}}},
    )
    assert reduced.status_code == 200
    rows = {item["vehicle_id"]: item for item in client.get("/api/progress").json()}
    assert rows[first["id"]] == {"vehicle_id": first["id"], "rp_earned": 10, "done": False}
    assert rows[second["id"]]["rp_earned"] == min(321, second["rp_cost"])


def test_progress_rejects_non_researchable_vehicles(client):
    registration = client.post(
        "/api/auth/register",
        json={"email": "invalid-progress@example.com", "password": "long-correct-horse"},
    )
    headers = {"X-CSRF-Token": registration.json()["csrf_token"]}
    vehicle = next(item for item in tree_nodes(client) if not item["rp_cost"])

    response = client.put(
        "/api/progress",
        headers=headers,
        json={"progress": {str(vehicle["id"]): {"rp_earned": 99_999_999, "done": True}}},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["vehicle_ids"] == [vehicle["id"]]
    with SessionLocal() as session:
        assert (
            session.scalar(select(UserVehicleProgress).where(UserVehicleProgress.vehicle_id == vehicle["id"])) is None
        )

    missing = client.put(
        "/api/progress",
        headers=headers,
        json={"progress": {"99999999": {"rp_earned": 1, "done": False}}},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["vehicle_ids"] == [99_999_999]


def test_duplicate_registration_is_a_controlled_conflict(client):
    payload = {"email": "Duplicate@Example.com", "password": "long-correct-horse"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    duplicate = client.post(
        "/api/auth/register",
        json={"email": "duplicate@example.com", "password": "long-correct-horse"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "An account with this email already exists."


def test_sqlite_enforces_foreign_keys(client):
    with SessionLocal() as session:
        session.add(UserVehicleProgress(user_id=999_999, vehicle_id=999_999, rp_earned=1))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_session_is_hashed_csrf_is_required_and_logout_revokes(client):
    registration = client.post(
        "/api/auth/register",
        json={"email": "session@example.com", "password": "long-correct-horse"},
    )
    raw_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    assert raw_cookie
    with SessionLocal() as session:
        stored = session.scalar(select(UserSession))
        assert stored is not None
        assert stored.token_hash != raw_cookie
        assert len(stored.token_hash) == 64

    vehicle = next(item for item in tree_nodes(client) if item["rp_cost"])
    rejected = client.put(
        "/api/progress",
        json={"progress": {str(vehicle["id"]): {"rp_earned": 1, "done": False}}},
    )
    assert rejected.status_code == 403

    logout = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": registration.json()["csrf_token"]},
    )
    assert logout.status_code == 200
    client.cookies.set(SESSION_COOKIE_NAME, raw_cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_non_ascii_csrf_header_is_a_controlled_rejection(client):
    client.post(
        "/api/auth/register",
        json={"email": "unicode-csrf@example.com", "password": "long-correct-horse"},
    )
    vehicle = next(item for item in tree_nodes(client) if item["rp_cost"])

    response = client.put(
        "/api/progress",
        headers={b"X-CSRF-Token": "niepoprawny-ą-token".encode()},
        json={"progress": {str(vehicle["id"]): {"rp_earned": 1, "done": False}}},
    )

    assert response.status_code == 403


def test_passwords_use_argon2id_and_legacy_hashes_upgrade_on_login(client):
    client.post(
        "/api/auth/register",
        json={"email": "argon@example.com", "password": "long-correct-horse"},
    )
    with SessionLocal() as session:
        registered = session.scalar(select(User).where(User.email == "argon@example.com"))
        assert registered is not None
        assert registered.password_hash.startswith("$argon2id$")
        assert "long-correct-horse" not in registered.password_hash
        legacy = User(
            email="legacy@example.com",
            password_hash=generate_password_hash("legacy-correct-horse"),
        )
        session.add(legacy)
        session.commit()

    login = client.post(
        "/api/auth/login",
        json={"email": "legacy@example.com", "password": "legacy-correct-horse"},
    )
    assert login.status_code == 200
    with SessionLocal() as session:
        upgraded = session.scalar(select(User).where(User.email == "legacy@example.com"))
        assert upgraded is not None
        assert upgraded.password_hash.startswith("$argon2id$")


def test_expired_session_and_login_throttling(client):
    registration = client.post(
        "/api/auth/register",
        json={"email": "expiry@example.com", "password": "long-correct-horse"},
    )
    assert registration.status_code == 201
    with SessionLocal() as session:
        stored = session.scalar(select(UserSession).where(UserSession.user_id == registration.json()["user"]["id"]))
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert client.get("/api/auth/me").status_code == 401

    for _ in range(5):
        failed = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
        )
        assert failed.status_code == 401
    blocked = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_import_is_idempotent(client):
    before = len(tree_nodes(client))
    with SessionLocal() as session:
        import_from_json_dict(session, build_normalized_snapshot(FIXTURE, minimum_vehicles=1))
    after = len(tree_nodes(client))
    assert after == before


def test_non_researchable_vehicle_returns_validation_error(client):
    vehicle = next(item for item in tree_nodes(client) if item["name"] == "M2A4")
    response = client.post(
        "/api/calc/estimate",
        json={"vehicle_id": vehicle["id"], "avg_rp_per_battle": 1000},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "This vehicle has no research RP cost and cannot be a target."

    cascade = client.post(
        "/api/calc/cascade",
        json={"vehicle_id": vehicle["id"], "avg_rp_per_battle": 1000},
    )
    assert cascade.status_code == 422
    assert cascade.json()["detail"] == "This vehicle has no research RP cost and cannot be a target."


def test_cascade_does_not_assume_the_research_vehicle_is_unlocked(client):
    tree = client.get("/api/tree", params={"nation": "usa", "class": "army"}).json()
    vehicles = {item["id"]: item for item in tree["nodes"]}
    edge = next(
        item for item in tree["edges"] if vehicles[item["parent"]]["rp_cost"] and vehicles[item["child"]]["rp_cost"]
    )
    research_vehicle = vehicles[edge["parent"]]

    response = client.post(
        "/api/calc/cascade",
        json={
            "vehicle_id": edge["child"],
            "research_vehicle_id": research_vehicle["id"],
            "avg_rp_per_battle": 1_000,
            "progress": {},
        },
    )

    assert response.status_code == 200
    row = next(item for item in response.json()["breakdown"] if item["id"] == research_vehicle["id"])
    assert row["done"] is False
    assert row["rp_remaining"] == research_vehicle["rp_cost"]


def test_cascade_treats_reserve_prerequisites_as_unlocked(client):
    tree = client.get("/api/tree", params={"nation": "usa", "class": "army"}).json()
    vehicles = {item["id"]: item for item in tree["nodes"]}
    edge = next(item for item in tree["edges"] if vehicles[item["parent"]]["is_reserve"])

    response = client.post(
        "/api/calc/cascade",
        json={"vehicle_id": edge["child"], "avg_rp_per_battle": 1_000, "progress": {}},
    )

    assert response.status_code == 200
    reserve = next(item for item in response.json()["breakdown"] if item["id"] == edge["parent"])
    assert reserve["done"] is True
    assert reserve["rp_remaining"] == 0


def test_cascade_uses_top_level_target_progress_when_progress_map_omits_it(client):
    target = next(item for item in tree_nodes(client) if item["rp_cost"])
    current = target["rp_cost"] - 1

    response = client.post(
        "/api/calc/cascade",
        json={
            "vehicle_id": target["id"],
            "rp_current": current,
            "avg_rp_per_battle": 1_000,
            "progress": {},
        },
    )

    assert response.status_code == 200
    row = next(item for item in response.json()["breakdown"] if item["id"] == target["id"])
    assert row["rp_current"] == current
    assert row["rp_remaining"] == 1


def test_cascade_uses_a_fixed_query_budget_for_the_route(client):
    tree = client.get("/api/tree", params={"nation": "usa", "class": "army"}).json()
    candidates = [item for item in tree["nodes"] if item["rp_cost"]]
    target = max(candidates, key=lambda item: (item["rank"], item["id"]))
    research_vehicle = next(item for item in candidates if item["id"] != target["id"])
    selects: list[str] = []

    def count_selects(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        response = client.post(
            "/api/calc/cascade",
            json={
                "vehicle_id": target["id"],
                "research_vehicle_id": research_vehicle["id"],
                "avg_rp_per_battle": 1_000,
            },
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert response.status_code == 200
    assert len(selects) <= 5


def test_cascade_keeps_manual_cross_branch_prerequisites(client):
    tree = client.get("/api/tree", params={"nation": "usa", "class": "army"}).json()
    target = max(
        (item for item in tree["nodes"] if item["rp_cost"]),
        key=lambda item: (item["rank"], item["id"]),
    )
    with SessionLocal() as session:
        target_record = session.get(Vehicle, target["id"])
        assert target_record is not None
        cross_branch = VehicleClass(name="audit-cross-branch")
        session.add(cross_branch)
        session.flush()
        parent = Vehicle(
            source_key="manual-cross-branch-parent",
            source_name="manual-json",
            name="Manual cross-branch parent",
            nation_id=target_record.nation_id,
            class_id=cross_branch.id,
            rank_id=target_record.rank_id,
            is_tree=True,
            rp_cost=1_234,
        )
        session.add(parent)
        session.flush()
        session.add(VehicleEdge(parent_id=parent.id, child_id=target_record.id))
        session.commit()
        parent_id = parent.id

    response = client.post(
        "/api/calc/cascade",
        json={"vehicle_id": target["id"], "avg_rp_per_battle": 1_000},
    )

    assert response.status_code == 200
    assert parent_id in response.json()["required_ids"]


def test_retired_research_vehicle_is_rejected(client):
    candidates = [item for item in tree_nodes(client) if item["rp_cost"]]
    target, research_vehicle = candidates[:2]
    with SessionLocal() as session:
        stored = session.get(Vehicle, research_vehicle["id"])
        assert stored is not None
        stored.retired_at = utc_now()
        session.commit()

    response = client.post(
        "/api/calc/estimate",
        json={
            "vehicle_id": target["id"],
            "research_vehicle_id": research_vehicle["id"],
            "avg_rp_per_battle": 1_000,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The research vehicle is no longer available in the catalog."


def test_tree_metadata_comes_from_the_tree_source(client):
    with SessionLocal() as session:
        expected = session.scalar(select(CatalogSnapshot).where(CatalogSnapshot.source == "war-thunder-datamine"))
        assert expected is not None
        expected_version = expected.version
        session.add(
            CatalogSnapshot(
                source="unrelated-source",
                version="999.0",
                revision="unrelated-revision",
                checksum="f" * 64,
                imported_at=utc_now() + timedelta(days=1),
                vehicle_count=1,
                is_active=True,
            )
        )
        session.commit()

    response = client.get("/api/tree", params={"nation": "usa", "class": "army"})

    assert response.status_code == 200
    assert response.json()["meta"]["source_version"] == expected_version


def test_calculation_progress_has_a_bounded_input(client):
    vehicle = next(item for item in tree_nodes(client) if item["rp_cost"])
    response = client.post(
        "/api/calc/estimate",
        json={"vehicle_id": vehicle["id"], "rp_current": 100_000_001, "avg_rp_per_battle": 1000},
    )
    assert response.status_code == 422


def test_removed_dead_endpoints_are_not_exposed(client):
    assert client.get("/api/ranks").status_code == 404
    assert client.get("/api/vehicles").status_code == 404
    assert client.get("/api/profile").status_code == 404


def test_chunked_request_limit_and_early_errors_have_security_headers(client):
    response = client.post("/api/auth/login", content=b"x" * 1_100_000)
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")

    sent: list[dict] = []
    messages = iter(
        [
            {"type": "http.request", "body": b'{"email":"' + b"a" * 600_000, "more_body": True},
            {
                "type": "http.request",
                "body": b"a" * 600_000 + b'@example.com","password":"wrong-password"}',
                "more_body": False,
            },
        ]
    )

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 413
    headers = dict(sent[0]["headers"])
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    assert json.loads(body) == {"error": "Request body is too large."}

    unrelated = client.get("/api/authors")
    assert unrelated.status_code == 404
    assert "cache-control" not in unrelated.headers

    with TestClient(app, base_url="https://testserver") as secure_client:
        secure = secure_client.get("/api/health")
        assert secure.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_forwarded_ip_is_used_only_for_a_trusted_proxy(monkeypatch):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"198.51.100.7, 10.0.0.2")],
        "client": ("10.0.0.3", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
        "root_path": "",
    }
    request = Request(scope)
    monkeypatch.setattr(security, "TRUSTED_PROXY_NETWORKS", (ipaddress.ip_network("10.0.0.0/8"),))
    assert client_ip(request) == "198.51.100.7"

    monkeypatch.setattr(security, "TRUSTED_PROXY_NETWORKS", ())
    assert client_ip(request) == "10.0.0.3"


def test_one_ip_cannot_lock_an_account_out_globally(client):
    credentials = {"email": "victim@example.com", "password": "long-correct-horse"}
    assert client.post("/api/auth/register", json=credentials).status_code == 201

    with TestClient(app, client=("198.51.100.10", 50000)) as attacker:
        for _ in range(5):
            assert (
                attacker.post(
                    "/api/auth/login",
                    json={"email": credentials["email"], "password": "wrong-password"},
                ).status_code
                == 401
            )
        assert (
            attacker.post(
                "/api/auth/login",
                json={"email": credentials["email"], "password": "wrong-password"},
            ).status_code
            == 429
        )

    with TestClient(app, client=("203.0.113.20", 50000)) as victim:
        assert victim.post("/api/auth/login", json=credentials).status_code == 200


def test_registration_throttle_returns_429(client):
    for index in range(10):
        response = client.post(
            "/api/auth/register",
            json={"email": f"registration-{index}@example.com", "password": "long-correct-horse"},
        )
        assert response.status_code == 201
    blocked = client.post(
        "/api/auth/register",
        json={"email": "registration-blocked@example.com", "password": "long-correct-horse"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_registration_throttle_counts_parallel_attempts_atomically(tmp_path):
    isolated_engine = create_engine(
        f"sqlite:///{(tmp_path / 'throttle.db').as_posix()}",
        connect_args={"timeout": 15},
    )
    AuthThrottle.__table__.create(isolated_engine)
    isolated_session = sessionmaker(bind=isolated_engine, expire_on_commit=False)

    def attempt(_: int) -> int | None:
        with isolated_session() as session:
            return security.consume_registration_attempt(session, "198.51.100.50")

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(attempt, range(16)))
        assert sum(result is None for result in results) == 10
        assert all(result is None or result > 0 for result in results)
    finally:
        isolated_engine.dispose()


def test_samesite_none_cookie_configuration(monkeypatch, client):
    monkeypatch.setattr(security, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(security, "SESSION_COOKIE_SAMESITE", "none")
    response = client.post(
        "/api/auth/register",
        json={"email": "cross-site@example.com", "password": "long-correct-horse"},
    )
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=none" in cookie


def test_session_cleanup_accepts_legacy_naive_sqlite_datetimes(client):
    with SessionLocal() as session:
        user = User(email="cleanup@example.com", password_hash=security.hash_password("long-correct-horse"))
        session.add(user)
        session.flush()
        old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60)
        session.add(
            UserSession(
                user_id=user.id,
                token_hash="a" * 64,
                created_at=old,
                last_seen_at=old,
                expires_at=old,
            )
        )
        session.add(
            AuthThrottle(
                key_hash="b" * 64,
                failures=1,
                window_started_at=old,
                updated_at=old,
            )
        )
        session.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": "cleanup@example.com", "password": "long-correct-horse"},
    )
    assert response.status_code == 200
    with SessionLocal() as session:
        assert session.scalar(select(UserSession).where(UserSession.token_hash == "a" * 64)) is None
        assert session.get(AuthThrottle, "b" * 64) is None

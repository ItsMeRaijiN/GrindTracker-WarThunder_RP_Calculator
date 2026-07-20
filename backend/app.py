from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from calc import Forecast, estimate_cascade, estimate_vehicle, rank_efficiency_rules, summarize_recent_battles
from catalog import is_temporary_variant
from database import assert_database_current, get_db, init_db
from middleware import RequestBodyTooLarge, RequestSecurityMiddleware
from models import (
    CatalogSnapshot,
    Nation,
    User,
    UserVehicleProgress,
    Vehicle,
    VehicleClass,
    VehicleEdge,
    utc_now,
)
from schemas import CalcPayload, LoginPayload, ProgressBulkPayload, ProgressPayload, RegisterPayload
from security import (
    ENVIRONMENT,
    SESSION_COOKIE_NAME,
    SessionContext,
    clear_login_throttle,
    clear_session_cookie,
    client_ip,
    consume_registration_attempt,
    csrf_token,
    hash_password,
    issue_session,
    load_session,
    record_login_failure,
    revoke_session,
    throttle_keys,
    throttle_retry_after,
    verify_csrf,
    verify_dummy_password,
    verify_password,
)


def _boolean_environment(name: str, default: bool) -> bool:
    value = os.getenv(name, "true" if default else "false").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")


MIGRATE_ON_STARTUP = _boolean_environment("MIGRATE_ON_STARTUP", ENVIRONMENT != "production")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if MIGRATE_ON_STARTUP:
        init_db()
    else:
        assert_database_current()
    yield


app = FastAPI(
    title="GrindTracker API",
    version="1.0.0",
    description="Typed API for War Thunder research planning.",
    lifespan=lifespan,
)

allowed_origins = [
    value.strip()
    for value in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if value.strip()
]
if "*" in allowed_origins:
    raise RuntimeError("CORS_ORIGINS cannot contain '*' when cookie authentication is enabled.")


def _validate_origin(origin: str) -> None:
    parsed = urlsplit(origin)
    has_extra_parts = bool(parsed.path or parsed.query or parsed.fragment)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or has_extra_parts:
        raise RuntimeError(f"Invalid CORS origin: {origin!r}. Use an origin without a path or trailing slash.")
    if parsed.username or parsed.password:
        raise RuntimeError("CORS_ORIGINS must not contain credentials.")
    if ENVIRONMENT == "production" and parsed.scheme != "https":
        raise RuntimeError("Production CORS_ORIGINS must use HTTPS.")


for configured_origin in allowed_origins:
    _validate_origin(configured_origin)
# noinspection PyTypeChecker
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

default_hosts = "localhost,127.0.0.1,testserver" if ENVIRONMENT != "production" else ""
trusted_hosts = [value.strip() for value in os.getenv("TRUSTED_HOSTS", default_hosts).split(",") if value.strip()]
if not trusted_hosts:
    raise RuntimeError("TRUSTED_HOSTS must list the API host names.")
if ENVIRONMENT == "production" and "*" in trusted_hosts:
    raise RuntimeError("Production TRUSTED_HOSTS cannot contain '*'.")
# noinspection PyTypeChecker
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

try:
    max_request_bytes = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
except ValueError as configuration_error:
    raise RuntimeError("MAX_REQUEST_BYTES must be an integer.") from configuration_error
if not 16_384 <= max_request_bytes <= 10_485_760:
    raise RuntimeError("MAX_REQUEST_BYTES must be between 16384 and 10485760.")
app.add_middleware(RequestSecurityMiddleware, max_request_bytes=max_request_bytes)


@app.exception_handler(RequestBodyTooLarge)
async def request_body_too_large(_: Request, request_error: RequestBodyTooLarge) -> JSONResponse:
    return JSONResponse(status_code=request_error.status_code, content={"error": str(request_error.detail)})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, request_error: RequestValidationError) -> JSONResponse:
    details = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in request_error.errors()]
    return JSONResponse(status_code=422, content={"error": "Invalid input.", "details": details})


SessionDep = Annotated[Session, Depends(get_db)]


def current_auth(request: Request, session: SessionDep) -> SessionContext:
    context = load_session(session, request.cookies.get(SESSION_COOKIE_NAME))
    if context is None:
        raise HTTPException(status_code=401, detail="The session is missing, invalid or has expired.")
    return context


AuthDep = Annotated[SessionContext, Depends(current_auth)]


def csrf_auth(request: Request, auth: AuthDep) -> SessionContext:
    if not verify_csrf(auth.raw_token, request.headers.get("X-CSRF-Token")):
        raise HTTPException(status_code=403, detail="The CSRF token is missing or invalid.")
    return auth


CsrfAuthDep = Annotated[SessionContext, Depends(csrf_auth)]


def current_user(auth: AuthDep) -> User:
    return auth.user


def csrf_user(auth: CsrfAuthDep) -> User:
    return auth.user


UserDep = Annotated[User, Depends(current_user)]
CsrfUserDep = Annotated[User, Depends(csrf_user)]


def vehicle_dict(vehicle: Vehicle) -> dict[str, Any]:
    return {
        "id": vehicle.id,
        "name": vehicle.name,
        "nation": vehicle.nation.slug,
        "class": vehicle.vehicle_class.name,
        "rank": vehicle.rank_id,
        "type": vehicle.type_str,
        "is_reserve": vehicle.is_reserve,
        "availability": vehicle.availability,
        "tree_column": vehicle.tree_column,
        "tree_order": vehicle.tree_order,
        "br": {"ab": vehicle.br_ab, "rb": vehicle.br_rb, "sb": vehicle.br_sb},
        "rp_multiplier": vehicle.rp_multiplier,
        "rp_cost": vehicle.rp_cost,
        "ge_cost": vehicle.ge_cost,
        "gjn_cost": vehicle.gjn_cost,
        "marketplace_item_id": vehicle.marketplace_item_id,
        "folder_of": vehicle.folder_of,
    }


def research_column_count(rows: list[Vehicle], edges: list[VehicleEdge]) -> int:
    """Find the contiguous source columns that form the main research tree."""
    columns = sorted({item.tree_column for item in rows if item.tree_column is not None})
    if not columns:
        return 0
    edge_vehicle_ids = {vehicle_id for edge in edges for vehicle_id in (edge.parent_id, edge.child_id)}
    main_columns: set[int] = set()
    for column in columns:
        column_rows = [item for item in rows if item.tree_column == column]
        tree_count = sum(item.is_tree for item in column_rows)
        if tree_count > len(column_rows) - tree_count:
            main_columns.add(column)
        if any(item.is_tree and item.id in edge_vehicle_ids for item in column_rows):
            main_columns.add(column)
    if not main_columns:
        return len(columns)
    last_main_column = max(main_columns)
    return sum(column <= last_main_column for column in columns)


def build_forecast(payload: CalcPayload) -> tuple[Forecast, int]:
    recent = [item.model_dump() for item in payload.recent_battles]
    avg_rp, avg_minutes, samples = summarize_recent_battles(recent)
    return Forecast(
        avg_rp_per_battle=avg_rp if samples else payload.avg_rp_per_battle,
        avg_battle_minutes=avg_minutes if samples else payload.avg_battle_minutes,
        rp_is_base=payload.rp_is_base,
        has_premium=payload.has_premium,
        booster_percent=payload.booster_percent,
        skill_bonus_percent=payload.skill_bonus_percent,
        has_talisman=payload.has_talisman,
        game_mode=payload.game_mode,
    ), samples


def research_vehicle_for(session: Session, payload: CalcPayload, target: Vehicle) -> Vehicle | None:
    if payload.research_vehicle_id is None:
        return None
    research_vehicle = cast(Vehicle | None, session.get(Vehicle, payload.research_vehicle_id))
    if research_vehicle is None:
        raise HTTPException(status_code=404, detail="Research vehicle not found.")
    if research_vehicle.retired_at is not None:
        raise HTTPException(status_code=422, detail="The research vehicle is no longer available in the catalog.")
    if research_vehicle.id == target.id:
        raise HTTPException(status_code=422, detail="The target cannot also be the research vehicle.")
    if research_vehicle.nation_id != target.nation_id or research_vehicle.class_id != target.class_id:
        raise HTTPException(status_code=422, detail="The research vehicle must belong to the same nation and branch.")
    return research_vehicle


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "GrindTracker API", "status": "ok", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
def health(session: SessionDep) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload, request: Request, response: Response, session: SessionDep) -> dict[str, Any]:
    address = client_ip(request)
    retry_after = consume_registration_attempt(session, address)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    email = payload.email
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(payload.password))
    session.add(user)
    try:
        session.flush()
    except IntegrityError as integrity_error:
        session.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from integrity_error
    raw_token = issue_session(session, user, response, request.cookies.get(SESSION_COOKIE_NAME))
    return {"csrf_token": csrf_token(raw_token), "user": {"id": user.id, "email": user.email}}


@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request, response: Response, session: SessionDep) -> dict[str, Any]:
    email = payload.email
    address = client_ip(request)
    keys = throttle_keys(email, address)
    retry_after = throttle_retry_after(session, keys)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    # noinspection PyUnnecessaryCast
    user = cast(User | None, session.scalar(select(User).where(User.email == email)))
    if user is None:
        verify_dummy_password(payload.password)
        record_login_failure(session, keys)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    password = verify_password(user.password_hash, payload.password)
    if not password.valid:
        record_login_failure(session, keys)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    clear_login_throttle(session, email, address)
    if password.replacement_hash:
        user.password_hash = password.replacement_hash
        session.commit()
    raw_token = issue_session(session, user, response, request.cookies.get(SESSION_COOKIE_NAME))
    return {"csrf_token": csrf_token(raw_token), "user": {"id": user.id, "email": user.email}}


@app.get("/api/auth/me")
def me(auth: AuthDep) -> dict[str, Any]:
    return {"csrf_token": csrf_token(auth.raw_token), "user": {"id": auth.user.id, "email": auth.user.email}}


@app.post("/api/auth/logout")
def logout(response: Response, auth: CsrfAuthDep, session: SessionDep) -> dict[str, bool]:
    revoke_session(session, auth)
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/nations")
def nations(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(Nation).order_by(Nation.name)).all()
    return [{"id": item.id, "slug": item.slug, "name": item.name} for item in rows]


@app.get("/api/classes")
def classes(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(VehicleClass).order_by(VehicleClass.name)).all()
    return [{"id": item.id, "name": item.name} for item in rows]


@app.get("/api/tree")
def tree(
    session: SessionDep,
    nation: Annotated[str, Query(min_length=1, max_length=32)],
    vehicle_class: Annotated[str, Query(alias="class", min_length=1, max_length=32)],
) -> dict[str, Any]:
    rows = (
        session.scalars(
            select(Vehicle)
            .join(Nation)
            .join(VehicleClass)
            .where(
                Nation.slug == nation,
                VehicleClass.name == vehicle_class,
                Vehicle.retired_at.is_(None),
            )
            .order_by(Vehicle.tree_column, Vehicle.tree_order, Vehicle.rank_id, Vehicle.name)
        )
        .unique()
        .all()
    )
    rows = [item for item in rows if not is_temporary_variant(item.source_key, item.availability)]
    ids = {item.id for item in rows}
    edges = (
        session.scalars(
            select(VehicleEdge)
            .where(VehicleEdge.parent_id.in_(ids), VehicleEdge.child_id.in_(ids))
            .order_by(VehicleEdge.id)
        ).all()
        if ids
        else []
    )
    source_names = {item.source_name for item in rows if item.source_name}
    snapshot_query = select(CatalogSnapshot).where(CatalogSnapshot.is_active.is_(True))
    if source_names:
        snapshot_query = snapshot_query.where(CatalogSnapshot.source.in_(source_names))
    # noinspection PyUnnecessaryCast
    snapshot = cast(
        CatalogSnapshot | None,
        session.scalar(snapshot_query.order_by(CatalogSnapshot.imported_at.desc())),
    )
    return {
        "nodes": [vehicle_dict(item) for item in rows],
        "edges": [{"parent": edge.parent_id, "child": edge.child_id, "unlock_rp": edge.unlock_rp} for edge in edges],
        "meta": {
            "nation": nation,
            "class": vehicle_class,
            "vehicle_count": len(rows),
            "research_column_count": research_column_count(rows, edges),
            "research_efficiency": rank_efficiency_rules(),
            "source_version": snapshot.version if snapshot else None,
            "source_revision": snapshot.revision if snapshot else None,
            "updated_at": snapshot.imported_at.isoformat() if snapshot else None,
        },
    }


@app.post("/api/calc/estimate")
def estimate(payload: CalcPayload, session: SessionDep) -> dict[str, Any]:
    vehicle = cast(Vehicle | None, session.get(Vehicle, payload.vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if vehicle.retired_at is not None or not vehicle.rp_cost:
        raise HTTPException(status_code=422, detail="This vehicle has no research RP cost and cannot be a target.")
    research_vehicle = research_vehicle_for(session, payload, vehicle)
    forecast, samples = build_forecast(payload)
    return estimate_vehicle(session, vehicle, payload.rp_current, forecast, samples, research_vehicle)


@app.post("/api/calc/cascade")
def cascade(payload: CalcPayload, session: SessionDep) -> dict[str, Any]:
    vehicle = cast(Vehicle | None, session.get(Vehicle, payload.vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if vehicle.retired_at is not None or not vehicle.rp_cost:
        raise HTTPException(status_code=422, detail="This vehicle has no research RP cost and cannot be a target.")
    research_vehicle = research_vehicle_for(session, payload, vehicle)
    forecast, samples = build_forecast(payload)
    progress = {key: (value.rp_current, value.done) for key, value in payload.progress.items()}
    progress.setdefault(vehicle.id, (payload.rp_current, False))
    return estimate_cascade(session, vehicle, progress, forecast, samples, research_vehicle)


@app.get("/api/progress")
def get_progress(user: UserDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(UserVehicleProgress)
        .join(Vehicle, Vehicle.id == UserVehicleProgress.vehicle_id)
        .where(
            UserVehicleProgress.user_id == user.id,
            Vehicle.is_tree.is_(True),
            Vehicle.rp_cost > 0,
            Vehicle.retired_at.is_(None),
        )
    ).all()
    return [
        {
            "vehicle_id": item.vehicle_id,
            "rp_earned": item.rp_earned,
            "done": item.status == "unlocked",
        }
        for item in rows
    ]


def progress_values(vehicle: Vehicle, payload: ProgressPayload, user_id: int) -> tuple[dict[str, Any], bool]:
    total = max(0, int(vehicle.rp_cost or 0))
    earned = min(payload.rp_earned, total) if total else payload.rp_earned
    done = payload.done or 0 < total <= earned
    earned = total if done and total else earned
    return {
        "user_id": user_id,
        "vehicle_id": vehicle.id,
        "rp_earned": earned,
        "status": "unlocked" if done else ("researching" if earned else "locked"),
        "last_seen_at": utc_now(),
    }, done


@app.put("/api/progress")
def save_progress_bulk(
    payload: ProgressBulkPayload,
    user: CsrfUserDep,
    session: SessionDep,
) -> dict[str, list[dict[str, Any]]]:
    vehicle_ids = list(payload.progress)
    if not vehicle_ids:
        return {"items": []}
    vehicles = session.scalars(select(Vehicle).where(Vehicle.id.in_(vehicle_ids))).all()
    vehicle_map = {vehicle.id: vehicle for vehicle in vehicles}
    missing = sorted(set(vehicle_ids) - set(vehicle_map))
    if missing:
        shown = ", ".join(map(str, missing[:20]))
        suffix = "…" if len(missing) > 20 else ""
        raise HTTPException(
            status_code=404,
            detail={"message": f"Vehicle IDs not found: {shown}{suffix}", "vehicle_ids": missing},
        )

    invalid = sorted(
        vehicle_id
        for vehicle_id, vehicle in vehicle_map.items()
        if not vehicle.is_tree or vehicle.retired_at is not None or not vehicle.rp_cost
    )
    if invalid:
        shown = ", ".join(map(str, invalid[:20]))
        suffix = "…" if len(invalid) > 20 else ""
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Progress can only be saved for active researchable vehicles: {shown}{suffix}",
                "vehicle_ids": invalid,
            },
        )

    values: list[dict[str, Any]] = []
    result: list[dict[str, Any]] = []
    for vehicle_id, value in payload.progress.items():
        row, done = progress_values(vehicle_map[vehicle_id], value, user.id)
        values.append(row)
        result.append({"vehicle_id": vehicle_id, "rp_earned": row["rp_earned"], "done": done})

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(UserVehicleProgress).values(values)
    elif dialect == "postgresql":
        statement = postgresql_insert(UserVehicleProgress).values(values)
    else:
        raise RuntimeError(f"Atomic progress synchronization is not supported for database dialect {dialect!r}.")
    statement = statement.on_conflict_do_update(
        index_elements=[UserVehicleProgress.user_id, UserVehicleProgress.vehicle_id],
        set_={
            "rp_earned": statement.excluded.rp_earned,
            "status": statement.excluded.status,
            "last_seen_at": statement.excluded.last_seen_at,
        },
    )
    session.execute(statement)
    session.commit()
    return {"items": result}

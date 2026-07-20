from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request, Response
from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from models import AuthThrottle, User, UserSession

APP_DIR = Path(__file__).resolve().parent
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
if ENVIRONMENT not in {"development", "test", "production"}:
    raise RuntimeError("ENVIRONMENT must be development, test or production.")


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _boolean_setting(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")


def _load_secret() -> str:
    configured = os.getenv("SECRET_KEY", "").strip()
    if configured:
        if configured == "replace-with-at-least-32-random-bytes":
            raise RuntimeError("Replace the example SECRET_KEY before starting the API.")
        if len(configured) < 32:
            raise RuntimeError("SECRET_KEY must contain at least 32 characters.")
        return configured
    if ENVIRONMENT == "production":
        raise RuntimeError("Production requires an explicit SECRET_KEY from a secrets manager.")
    path = APP_DIR / "instance" / "secret.key"
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) < 32:
            raise RuntimeError("The generated instance/secret.key is invalid.")
        with suppress(OSError):
            path.chmod(0o600)
        return value
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    with suppress(OSError):
        path.chmod(0o600)
    return value


SECRET_KEY = _load_secret()
SESSION_COOKIE_SECURE = _boolean_setting("SESSION_COOKIE_SECURE", ENVIRONMENT == "production")
if ENVIRONMENT == "production" and not SESSION_COOKIE_SECURE:
    raise RuntimeError("Production sessions require SESSION_COOKIE_SECURE=true and HTTPS.")

default_cookie_name = "__Host-grindtracker_session" if SESSION_COOKIE_SECURE else "grindtracker_session"
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", default_cookie_name).strip()
if not SESSION_COOKIE_NAME:
    raise RuntimeError("SESSION_COOKIE_NAME cannot be empty.")
CookieSameSite = Literal["lax", "strict", "none"]
cookie_samesite = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
if cookie_samesite not in {"lax", "strict", "none"}:
    raise RuntimeError("SESSION_COOKIE_SAMESITE must be lax, strict or none.")
SESSION_COOKIE_SAMESITE: CookieSameSite = cookie_samesite
if SESSION_COOKIE_SAMESITE == "none" and not SESSION_COOKIE_SECURE:
    raise RuntimeError("SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true.")
SESSION_ABSOLUTE_HOURS = _integer_setting("SESSION_ABSOLUTE_HOURS", 168, 1, 24 * 30)
SESSION_IDLE_MINUTES = _integer_setting("SESSION_IDLE_MINUTES", 720, 5, 24 * 60)
SESSION_TOUCH_MINUTES = 5


def _proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    values = [value.strip() for value in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if value.strip()]
    try:
        return tuple(ipaddress.ip_network(value, strict=False) for value in values)
    except ValueError as exc:
        raise RuntimeError("TRUSTED_PROXY_IPS must contain comma-separated IP addresses or CIDR networks.") from exc


TRUSTED_PROXY_NETWORKS = _proxy_networks()


PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16)
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


@dataclass(frozen=True)
class PasswordCheck:
    valid: bool
    replacement_hash: str | None = None


@dataclass(frozen=True)
class SessionContext:
    user: User
    record: UserSession
    raw_token: str


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> PasswordCheck:
    if stored_hash.startswith("$argon2"):
        try:
            valid = PASSWORD_HASHER.verify(stored_hash, password)
        except (InvalidHashError, VerificationError):
            return PasswordCheck(False)
        replacement = PASSWORD_HASHER.hash(password) if PASSWORD_HASHER.check_needs_rehash(stored_hash) else None
        return PasswordCheck(valid, replacement)

    try:
        valid = check_password_hash(stored_hash, password)
    except (TypeError, ValueError):
        valid = False
    return PasswordCheck(valid, PASSWORD_HASHER.hash(password) if valid else None)


def verify_dummy_password(password: str) -> None:
    with suppress(VerificationError):
        PASSWORD_HASHER.verify(DUMMY_PASSWORD_HASH, password)


def token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def csrf_token(raw_token: str) -> str:
    digest = hmac.digest(SECRET_KEY.encode("utf-8"), f"csrf:{raw_token}".encode(), "sha256")
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_csrf(raw_token: str, submitted: str | None) -> bool:
    if not submitted:
        return False
    try:
        submitted_bytes = submitted.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(csrf_token(raw_token).encode("ascii"), submitted_bytes)


def client_ip(request: Request) -> str:
    client = request.client
    peer_value = client.host if client is not None else "unknown"
    try:
        peer = ipaddress.ip_address(peer_value)
    except ValueError:
        return peer_value[:64]
    if not any(peer in network for network in TRUSTED_PROXY_NETWORKS):
        return peer.compressed

    forwarded = request.headers.get("X-Forwarded-For", "")
    if not forwarded or len(forwarded) > 1_000:
        return peer.compressed
    try:
        chain = [ipaddress.ip_address(value.strip()) for value in forwarded.split(",") if value.strip()]
    except ValueError:
        return peer.compressed
    if not chain or len(chain) > 20:
        return peer.compressed
    for candidate in reversed(chain):
        if not any(candidate in network for network in TRUSTED_PROXY_NETWORKS):
            return candidate.compressed
    return peer.compressed


def issue_session(db: Session, user: User, response: Response, previous_token: str | None = None) -> str:
    now = datetime.now(UTC)
    db.execute(delete(UserSession).where(UserSession.expires_at < _database_time(db, now - timedelta(days=30))))
    db.execute(delete(AuthThrottle).where(AuthThrottle.updated_at < _database_time(db, now - timedelta(days=2))))
    if previous_token:
        # noinspection PyUnnecessaryCast
        previous = cast(
            UserSession | None,
            db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(previous_token))),
        )
        if previous and previous.revoked_at is None:
            previous.revoked_at = now

    raw_token = secrets.token_urlsafe(48)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_digest(raw_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=SESSION_ABSOLUTE_HOURS),
        )
    )
    db.commit()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_ABSOLUTE_HOURS * 3600,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/",
    )
    return raw_token


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/",
    )


def load_session(db: Session, raw_token: str | None) -> SessionContext | None:
    if not raw_token or len(raw_token) > 256:
        return None
    # noinspection PyUnnecessaryCast
    record = cast(
        UserSession | None,
        db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(raw_token))),
    )
    if record is None or record.revoked_at is not None:
        return None

    now = datetime.now(UTC)
    expires_at = _aware(record.expires_at)
    last_seen_at = _aware(record.last_seen_at)
    if expires_at <= now or last_seen_at + timedelta(minutes=SESSION_IDLE_MINUTES) <= now:
        record.revoked_at = now
        db.commit()
        return None
    user = cast(User | None, db.get(User, record.user_id))
    if user is None:
        record.revoked_at = now
        db.commit()
        return None
    if last_seen_at + timedelta(minutes=SESSION_TOUCH_MINUTES) <= now:
        record.last_seen_at = now
        db.commit()
    return SessionContext(user=user, record=record, raw_token=raw_token)


def revoke_session(db: Session, context: SessionContext) -> None:
    if context.record.revoked_at is None:
        context.record.revoked_at = datetime.now(UTC)
        db.commit()


def throttle_keys(email: str, address: str) -> tuple[tuple[str, int], tuple[str, int]]:
    return (_private_key("account-ip", f"{email}:{address}"), 5), (_private_key("ip", address), 25)


def throttle_retry_after(db: Session, keys: tuple[tuple[str, int], ...]) -> int | None:
    now = datetime.now(UTC)
    retry_after = 0
    for key, _ in keys:
        row = cast(AuthThrottle | None, db.get(AuthThrottle, key))
        if row and row.blocked_until and _aware(row.blocked_until) > now:
            retry_after = max(retry_after, int((_aware(row.blocked_until) - now).total_seconds()) + 1)
    return retry_after or None


def record_login_failure(db: Session, keys: tuple[tuple[str, int], ...]) -> None:
    now = datetime.now(UTC)
    window = timedelta(minutes=15)
    for key, limit in keys:
        _increment_throttle(db, key, limit, now, window)
    db.commit()


def clear_login_throttle(db: Session, email: str, address: str) -> None:
    row = cast(AuthThrottle | None, db.get(AuthThrottle, _private_key("account-ip", f"{email}:{address}")))
    if row is not None:
        db.delete(row)
        db.commit()


def consume_registration_attempt(db: Session, address: str) -> int | None:
    key = _private_key("register", address)
    now = datetime.now(UTC)
    window = timedelta(hours=1)
    retry_after = throttle_retry_after(db, ((key, 10),))
    if retry_after:
        return retry_after
    failures, blocked_until = _increment_throttle(db, key, 11, now, window)
    db.commit()
    if failures <= 10 or blocked_until is None:
        return None
    return int((_aware(blocked_until) - now).total_seconds()) + 1


def _private_key(namespace: str, value: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"{namespace}:{value}".encode(), hashlib.sha256).hexdigest()


def _increment_throttle(
    db: Session,
    key: str,
    block_at: int,
    now: datetime,
    window: timedelta,
) -> tuple[int, datetime | None]:
    """Atomically add one attempt and return the persisted counter state."""
    dialect = db.get_bind().dialect.name
    values = {
        "key_hash": key,
        "failures": 0,
        "window_started_at": _database_time(db, now),
        "updated_at": _database_time(db, now),
    }
    if dialect == "sqlite":
        statement = sqlite_insert(AuthThrottle).values(values)
    elif dialect == "postgresql":
        statement = postgresql_insert(AuthThrottle).values(values)
    else:
        raise RuntimeError(f"Authentication throttling is not supported for database dialect {dialect!r}.")
    db.execute(statement.on_conflict_do_nothing(index_elements=[AuthThrottle.key_hash]))

    cutoff = _database_time(db, now - window)
    stored_now = _database_time(db, now)
    stored_blocked_until = _database_time(db, now + window)
    db.execute(
        update(AuthThrottle)
        .where(AuthThrottle.key_hash == key, AuthThrottle.window_started_at <= cutoff)
        .values(failures=0, window_started_at=stored_now, blocked_until=None, updated_at=stored_now)
    )
    next_failures = AuthThrottle.failures + 1
    row = db.execute(
        update(AuthThrottle)
        .where(AuthThrottle.key_hash == key)
        .values(
            failures=next_failures,
            blocked_until=case(
                (next_failures >= block_at, stored_blocked_until),
                else_=AuthThrottle.blocked_until,
            ),
            updated_at=stored_now,
        )
        .returning(AuthThrottle.failures, AuthThrottle.blocked_until)
    ).one()
    return int(row.failures), row.blocked_until


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _database_time(db: Session, value: datetime) -> datetime:
    return value.replace(tzinfo=None) if db.get_bind().dialect.name == "sqlite" else value

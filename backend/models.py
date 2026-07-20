from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Nation(Base):
    __tablename__ = "nations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    flag_url: Mapped[str | None] = mapped_column(String(500))


class VehicleClass(Base):
    __tablename__ = "vehicle_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)


class Rank(Base):
    __tablename__ = "ranks"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(16))


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    source_name: Mapped[str | None] = mapped_column(String(80), index=True)
    source_version: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    nation_id: Mapped[int] = mapped_column(ForeignKey("nations.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("vehicle_classes.id"), index=True)
    rank_id: Mapped[int] = mapped_column(ForeignKey("ranks.id"), index=True)

    is_tree: Mapped[bool] = mapped_column(Boolean, default=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    is_collector: Mapped[bool] = mapped_column(Boolean, default=False)
    folder_of: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    folder_key: Mapped[str | None] = mapped_column(String(160), index=True)

    role: Mapped[str | None] = mapped_column(String(64), index=True)
    availability: Mapped[str] = mapped_column(String(32), default="researchable", index=True)
    research_type: Mapped[str] = mapped_column(String(32), default="standard")
    tree_column: Mapped[int | None] = mapped_column(Integer)
    tree_order: Mapped[int | None] = mapped_column(Integer)

    br_ab: Mapped[float | None] = mapped_column(Float)
    br_rb: Mapped[float | None] = mapped_column(Float)
    br_sb: Mapped[float | None] = mapped_column(Float)
    rp_multiplier: Mapped[float | None] = mapped_column(Float)
    rp_cost: Mapped[int | None] = mapped_column(Integer)
    sl_cost: Mapped[int | None] = mapped_column(Integer)
    ge_cost: Mapped[int | None] = mapped_column(Integer)
    gjn_cost: Mapped[float | None] = mapped_column(Float)
    marketplace_item_id: Mapped[int | None] = mapped_column(Integer, index=True)
    image_url: Mapped[str | None] = mapped_column(String(500))
    wiki_url: Mapped[str | None] = mapped_column(String(500))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    nation: Mapped[Nation] = relationship(lazy="joined")
    vehicle_class: Mapped[VehicleClass] = relationship(lazy="joined")
    rank: Mapped[Rank] = relationship(lazy="joined")

    @property
    def is_reserve(self) -> bool:
        """Tree vehicles without a research cost are starter reserves."""
        return self.is_tree and self.rp_cost is None

    @property
    def type_str(self) -> str:
        if self.is_premium:
            return "premium"
        if self.is_collector:
            return "collector"
        return "tree"


class CatalogSnapshot(Base):
    __tablename__ = "catalog_snapshots"
    __table_args__ = (UniqueConstraint("source", "revision", name="uq_catalog_snapshot_source_revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[str] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(String(500))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    vehicle_count: Mapped[int] = mapped_column(Integer)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class VehicleEdge(Base):
    __tablename__ = "vehicle_edges"
    __table_args__ = (UniqueConstraint("parent_id", "child_id", name="uq_vehicle_edge"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    unlock_rp: Mapped[int | None] = mapped_column(Integer)
    source_name: Mapped[str | None] = mapped_column(String(80), index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sessions: Mapped[list[UserSession]] = relationship(cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AuthThrottle(Base):
    __tablename__ = "auth_throttles"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserVehicleProgress(Base):
    __tablename__ = "user_vehicle_progress"
    __table_args__ = (UniqueConstraint("user_id", "vehicle_id", name="uq_user_vehicle"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="locked")
    rp_earned: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

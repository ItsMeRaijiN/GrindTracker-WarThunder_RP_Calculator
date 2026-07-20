"""initial schema

Revision ID: ee341f3c76b7
Revises:
Create Date: 2026-07-19 17:13:28.376778
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ee341f3c76b7"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_throttles",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    with op.batch_alter_table("auth_throttles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_auth_throttles_blocked_until"), ["blocked_until"], unique=False)

    op.create_table(
        "catalog_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vehicle_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "revision", name="uq_catalog_snapshot_source_revision"),
    )
    with op.batch_alter_table("catalog_snapshots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_catalog_snapshots_is_active"), ["is_active"], unique=False)
        batch_op.create_index(batch_op.f("ix_catalog_snapshots_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_catalog_snapshots_version"), ["version"], unique=False)

    op.create_table(
        "nations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("flag_url", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("nations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_nations_slug"), ["slug"], unique=True)

    op.create_table(
        "ranks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "vehicle_classes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("vehicle_classes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vehicle_classes_name"), ["name"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("user_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_sessions_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_sessions_revoked_at"), ["revoked_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_sessions_token_hash"), ["token_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_user_sessions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=160), nullable=True),
        sa.Column("source_name", sa.String(length=80), nullable=True),
        sa.Column("source_version", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("nation_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("rank_id", sa.Integer(), nullable=False),
        sa.Column("is_tree", sa.Boolean(), nullable=False),
        sa.Column("is_premium", sa.Boolean(), nullable=False),
        sa.Column("is_collector", sa.Boolean(), nullable=False),
        sa.Column("folder_of", sa.Integer(), nullable=True),
        sa.Column("folder_key", sa.String(length=160), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=True),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("research_type", sa.String(length=32), nullable=False),
        sa.Column("tree_column", sa.Integer(), nullable=True),
        sa.Column("tree_order", sa.Integer(), nullable=True),
        sa.Column("br_ab", sa.Float(), nullable=True),
        sa.Column("br_rb", sa.Float(), nullable=True),
        sa.Column("br_sb", sa.Float(), nullable=True),
        sa.Column("rp_multiplier", sa.Float(), nullable=True),
        sa.Column("rp_cost", sa.Integer(), nullable=True),
        sa.Column("sl_cost", sa.Integer(), nullable=True),
        sa.Column("ge_cost", sa.Integer(), nullable=True),
        sa.Column("gjn_cost", sa.Float(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("wiki_url", sa.String(length=500), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["vehicle_classes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["folder_of"],
            ["vehicles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["nation_id"],
            ["nations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["rank_id"],
            ["ranks.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vehicles_availability"), ["availability"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_class_id"), ["class_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_folder_key"), ["folder_key"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_folder_of"), ["folder_of"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_nation_id"), ["nation_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_rank_id"), ["rank_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_role"), ["role"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_source_key"), ["source_key"], unique=True)
        batch_op.create_index(batch_op.f("ix_vehicles_source_name"), ["source_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicles_source_version"), ["source_version"], unique=False)

    op.create_table(
        "user_vehicle_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rp_earned", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "vehicle_id", name="uq_user_vehicle"),
    )
    with op.batch_alter_table("user_vehicle_progress", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_vehicle_progress_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_vehicle_progress_vehicle_id"), ["vehicle_id"], unique=False)

    op.create_table(
        "vehicle_edges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("unlock_rp", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["vehicles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["vehicles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_id", "child_id", name="uq_vehicle_edge"),
    )
    with op.batch_alter_table("vehicle_edges", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vehicle_edges_child_id"), ["child_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicle_edges_parent_id"), ["parent_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("vehicle_edges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vehicle_edges_parent_id"))
        batch_op.drop_index(batch_op.f("ix_vehicle_edges_child_id"))

    op.drop_table("vehicle_edges")
    with op.batch_alter_table("user_vehicle_progress", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_vehicle_progress_vehicle_id"))
        batch_op.drop_index(batch_op.f("ix_user_vehicle_progress_user_id"))

    op.drop_table("user_vehicle_progress")
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vehicles_source_version"))
        batch_op.drop_index(batch_op.f("ix_vehicles_source_name"))
        batch_op.drop_index(batch_op.f("ix_vehicles_source_key"))
        batch_op.drop_index(batch_op.f("ix_vehicles_role"))
        batch_op.drop_index(batch_op.f("ix_vehicles_rank_id"))
        batch_op.drop_index(batch_op.f("ix_vehicles_nation_id"))
        batch_op.drop_index(batch_op.f("ix_vehicles_name"))
        batch_op.drop_index(batch_op.f("ix_vehicles_folder_of"))
        batch_op.drop_index(batch_op.f("ix_vehicles_folder_key"))
        batch_op.drop_index(batch_op.f("ix_vehicles_class_id"))
        batch_op.drop_index(batch_op.f("ix_vehicles_availability"))

    op.drop_table("vehicles")
    with op.batch_alter_table("user_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_sessions_user_id"))
        batch_op.drop_index(batch_op.f("ix_user_sessions_token_hash"))
        batch_op.drop_index(batch_op.f("ix_user_sessions_revoked_at"))
        batch_op.drop_index(batch_op.f("ix_user_sessions_expires_at"))

    op.drop_table("user_sessions")
    with op.batch_alter_table("vehicle_classes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vehicle_classes_name"))

    op.drop_table("vehicle_classes")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
    op.drop_table("ranks")
    with op.batch_alter_table("nations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_nations_slug"))

    op.drop_table("nations")
    with op.batch_alter_table("catalog_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_catalog_snapshots_version"))
        batch_op.drop_index(batch_op.f("ix_catalog_snapshots_source"))
        batch_op.drop_index(batch_op.f("ix_catalog_snapshots_is_active"))

    op.drop_table("catalog_snapshots")
    with op.batch_alter_table("auth_throttles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_auth_throttles_blocked_until"))

    op.drop_table("auth_throttles")

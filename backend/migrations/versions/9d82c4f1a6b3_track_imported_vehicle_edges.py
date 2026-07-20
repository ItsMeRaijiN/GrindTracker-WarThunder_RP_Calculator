"""Track importer-owned vehicle edges.

Revision ID: 9d82c4f1a6b3
Revises: 74d0c9a2e6f1
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d82c4f1a6b3"
down_revision: str | Sequence[str] | None = "74d0c9a2e6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("vehicle_edges")}
    indexes = {index["name"] for index in inspector.get_indexes("vehicle_edges")}
    index_name = op.f("ix_vehicle_edges_source_name")
    with op.batch_alter_table("vehicle_edges", schema=None) as batch_op:
        if "source_name" not in columns:
            batch_op.add_column(sa.Column("source_name", sa.String(length=80), nullable=True))
        if index_name not in indexes:
            batch_op.create_index(index_name, ["source_name"], unique=False)

    vehicle_edges = sa.table(
        "vehicle_edges",
        sa.column("child_id", sa.Integer()),
        sa.column("source_name", sa.String(length=80)),
    )
    vehicles = sa.table(
        "vehicles",
        sa.column("id", sa.Integer()),
        sa.column("source_name", sa.String(length=80)),
    )
    source_for_child = (
        sa.select(vehicles.c.source_name).where(vehicles.c.id == vehicle_edges.c.child_id).scalar_subquery()
    )
    op.execute(vehicle_edges.update().where(vehicle_edges.c.source_name.is_(None)).values(source_name=source_for_child))

    progress = sa.table(
        "user_vehicle_progress",
        sa.column("vehicle_id", sa.Integer()),
        sa.column("status", sa.String(length=24)),
    )
    op.execute(progress.update().where(progress.c.status == "purchased").values(status="unlocked"))
    valid_vehicles = sa.table(
        "vehicles",
        sa.column("id", sa.Integer()),
        sa.column("is_tree", sa.Boolean()),
        sa.column("rp_cost", sa.Integer()),
        sa.column("retired_at", sa.DateTime()),
    )
    valid_vehicle = sa.exists(
        sa.select(valid_vehicles.c.id).where(
            valid_vehicles.c.id == progress.c.vehicle_id,
            valid_vehicles.c.is_tree.is_(True),
            valid_vehicles.c.rp_cost > 0,
            valid_vehicles.c.retired_at.is_(None),
        )
    )
    op.execute(progress.delete().where(~valid_vehicle))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("vehicle_edges")}
    indexes = {index["name"] for index in inspector.get_indexes("vehicle_edges")}
    index_name = op.f("ix_vehicle_edges_source_name")
    with op.batch_alter_table("vehicle_edges", schema=None) as batch_op:
        if index_name in indexes:
            batch_op.drop_index(index_name)
        if "source_name" in columns:
            batch_op.drop_column("source_name")

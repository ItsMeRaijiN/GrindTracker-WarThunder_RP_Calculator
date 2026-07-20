"""Add the marketplace item marker to catalog vehicles.

Revision ID: 74d0c9a2e6f1
Revises: 1b7f8d2c4a10
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "74d0c9a2e6f1"
down_revision: str | Sequence[str] | None = "1b7f8d2c4a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("vehicles")}
    indexes = {index["name"] for index in inspector.get_indexes("vehicles")}
    index_name = op.f("ix_vehicles_marketplace_item_id")
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        if "marketplace_item_id" not in columns:
            batch_op.add_column(sa.Column("marketplace_item_id", sa.Integer(), nullable=True))
        if index_name not in indexes:
            batch_op.create_index(index_name, ["marketplace_item_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("vehicles")}
    indexes = {index["name"] for index in inspector.get_indexes("vehicles")}
    index_name = op.f("ix_vehicles_marketplace_item_id")
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        if index_name in indexes:
            batch_op.drop_index(index_name)
        if "marketplace_item_id" in columns:
            batch_op.drop_column("marketplace_item_id")

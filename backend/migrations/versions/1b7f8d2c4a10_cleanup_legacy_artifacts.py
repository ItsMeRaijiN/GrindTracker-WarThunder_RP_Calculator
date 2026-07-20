"""Remove artifacts left by pre-Alembic databases.

Revision ID: 1b7f8d2c4a10
Revises: ee341f3c76b7
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1b7f8d2c4a10"
down_revision: str | Sequence[str] | None = "ee341f3c76b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_profiles" in tables:
        op.drop_table("user_profiles")

    if "vehicles" in tables:
        columns = {column["name"] for column in inspector.get_columns("vehicles")}
        if "valid_from" in columns:
            op.drop_column("vehicles", "valid_from")


def downgrade() -> None:
    pass

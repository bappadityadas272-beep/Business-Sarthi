"""shop: name, size_sqft, city_tier (DEC-42)

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("shop", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("size_sqft", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("city_tier", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("shop", schema=None) as batch_op:
        batch_op.drop_column("city_tier")
        batch_op.drop_column("size_sqft")
        batch_op.drop_column("name")

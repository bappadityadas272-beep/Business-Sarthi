"""loan start_date and tenure_months (B-07, DEC-53)

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("loan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("tenure_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("loan", schema=None) as batch_op:
        batch_op.drop_column("tenure_months")
        batch_op.drop_column("start_date")

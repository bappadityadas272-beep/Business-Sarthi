"""shop opening_cash; review confidence, details and created_on (M-08, DEC-65, DEC-66)

Revision ID: 0005
Revises: 0004
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("shop", schema=None) as batch_op:
        batch_op.add_column(sa.Column("opening_cash", sa.Float(), nullable=True))
    with op.batch_alter_table("review", schema=None) as batch_op:
        batch_op.add_column(sa.Column("confidence", sa.String(length=8), nullable=False, server_default="low"))
        batch_op.add_column(sa.Column("details", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("created_on", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("review", schema=None) as batch_op:
        batch_op.drop_column("created_on")
        batch_op.drop_column("details")
        batch_op.drop_column("confidence")
    with op.batch_alter_table("shop", schema=None) as batch_op:
        batch_op.drop_column("opening_cash")

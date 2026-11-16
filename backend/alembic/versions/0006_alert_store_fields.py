"""alert params, dedupe key, dates and mute; notification created_at (B-08, DEC-67, DEC-68)

Revision ID: 0006
Revises: 0005
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("alert", schema=None) as batch_op:
        batch_op.add_column(sa.Column("params", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("dedupe_key", sa.String(length=64), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("raised_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("last_seen_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("cleared_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("resolved_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index("ix_alert_dedupe_key", ["dedupe_key"], unique=False)
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.drop_column("created_at")
    with op.batch_alter_table("alert", schema=None) as batch_op:
        batch_op.drop_index("ix_alert_dedupe_key")
        for col in ("muted", "resolved_on", "cleared_on", "last_seen_on", "raised_on", "dedupe_key", "params"):
            batch_op.drop_column(col)

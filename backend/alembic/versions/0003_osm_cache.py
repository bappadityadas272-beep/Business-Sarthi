"""osm_cache table (M-01)

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "osm_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cell", sa.String(length=32), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False),
        sa.Column("tags_version", sa.Integer(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cell", "radius_m", "tags_version", name="uq_osm_cache_cell"),
    )


def downgrade() -> None:
    op.drop_table("osm_cache")

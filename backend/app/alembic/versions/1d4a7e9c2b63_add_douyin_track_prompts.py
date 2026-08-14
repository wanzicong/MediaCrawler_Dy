"""Add an operating prompt to Douyin tracks.

Revision ID: 1d4a7e9c2b63
Revises: e74b2c9a5d18
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op


revision = "1d4a7e9c2b63"
down_revision = "e74b2c9a5d18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_track",
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("douyin_track", "prompt")

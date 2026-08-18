"""Add browser step screenshots to Douyin interaction events.

Revision ID: d21c7a4e9b36
Revises: 8e4b7d2c91a6
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op


revision = "d21c7a4e9b36"
down_revision = "8e4b7d2c91a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_interaction_event",
        sa.Column(
            "attempt_number", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "douyin_interaction_event",
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "douyin_interaction_event",
        sa.Column("screenshot_mime_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "douyin_interaction_event",
        sa.Column("screenshot_size", sa.Integer(), nullable=True),
    )
    op.add_column(
        "douyin_interaction_event",
        sa.Column("screenshot_sha256", sa.String(length=64), nullable=True),
    )
    op.alter_column(
        "douyin_interaction_event", "attempt_number", server_default=None
    )


def downgrade() -> None:
    op.drop_column("douyin_interaction_event", "screenshot_sha256")
    op.drop_column("douyin_interaction_event", "screenshot_size")
    op.drop_column("douyin_interaction_event", "screenshot_mime_type")
    op.drop_column("douyin_interaction_event", "screenshot_path")
    op.drop_column("douyin_interaction_event", "attempt_number")

"""Add persistent media migration state.

Revision ID: f47a8c1d9e20
Revises: e18c7a4b92d1
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "f47a8c1d9e20"
down_revision = "e18c7a4b92d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_media_asset",
        sa.Column(
            "migration_status",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column(
            "migration_progress", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column(
            "migration_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column("migration_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column("migration_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column("migration_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_douyin_media_asset_migration_status",
        "douyin_media_asset",
        ["migration_status"],
    )
    op.alter_column("douyin_media_asset", "migration_status", server_default=None)
    op.alter_column("douyin_media_asset", "migration_progress", server_default=None)
    op.alter_column(
        "douyin_media_asset", "migration_attempt_count", server_default=None
    )


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_media_asset_migration_status",
        table_name="douyin_media_asset",
    )
    op.drop_column("douyin_media_asset", "migration_finished_at")
    op.drop_column("douyin_media_asset", "migration_started_at")
    op.drop_column("douyin_media_asset", "migration_error")
    op.drop_column("douyin_media_asset", "migration_attempt_count")
    op.drop_column("douyin_media_asset", "migration_progress")
    op.drop_column("douyin_media_asset", "migration_status")

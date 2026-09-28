"""Add subtitle-only intent to media assets.

Revision ID: b4e7c1a9d2f3
Revises: 6d3f9a2c7e41
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op


revision = "b4e7c1a9d2f3"
down_revision = "6d3f9a2c7e41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """媒体资产新增 subtitle_only 标记（仅转字幕、不保留文件）。"""
    op.add_column(
        "douyin_media_asset",
        sa.Column(
            "subtitle_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("douyin_media_asset", "subtitle_only", server_default=None)


def downgrade() -> None:
    op.drop_column("douyin_media_asset", "subtitle_only")

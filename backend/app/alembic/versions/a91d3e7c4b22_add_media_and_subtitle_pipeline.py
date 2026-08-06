"""Add media download and subtitle pipeline tables.

Revision ID: a91d3e7c4b22
Revises: c7b3d6e4f210
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op


revision = "a91d3e7c4b22"
down_revision = "c7b3d6e4f210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_media_asset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("aweme_id", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "aweme_id", name="uq_douyin_media_task_aweme"),
    )
    op.create_index("ix_douyin_media_asset_task_id", "douyin_media_asset", ["task_id"])
    op.create_index("ix_douyin_media_asset_aweme_id", "douyin_media_asset", ["aweme_id"])
    op.create_index("ix_douyin_media_asset_status", "douyin_media_asset", ["status"])

    op.create_table(
        "douyin_subtitle",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("aweme_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("requested_backend", sa.String(length=32), nullable=False),
        sa.Column("actual_backend", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("segments_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["douyin_media_asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_douyin_subtitle_asset"),
    )
    op.create_index("ix_douyin_subtitle_asset_id", "douyin_subtitle", ["asset_id"])
    op.create_index("ix_douyin_subtitle_task_id", "douyin_subtitle", ["task_id"])
    op.create_index("ix_douyin_subtitle_aweme_id", "douyin_subtitle", ["aweme_id"])
    op.create_index("ix_douyin_subtitle_status", "douyin_subtitle", ["status"])


def downgrade() -> None:
    op.drop_table("douyin_subtitle")
    op.drop_table("douyin_media_asset")

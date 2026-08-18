"""Add Douyin crawler task and data tables.

Revision ID: c7b3d6e4f210
Revises: fe56fa70289e
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op


revision = "c7b3d6e4f210"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("aweme_count", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("action_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("qrcode_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_task_owner_id", "crawl_task", ["owner_id"])
    op.create_index("ix_crawl_task_crawl_type", "crawl_task", ["crawl_type"])
    op.create_index("ix_crawl_task_status", "crawl_task", ["status"])

    op.create_table(
        "douyin_aweme",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("aweme_id", sa.String(length=128), nullable=False),
        sa.Column("aweme_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("create_time", sa.Integer(), nullable=True),
        sa.Column("creator_hash", sa.String(length=64), nullable=False),
        sa.Column("sec_uid", sa.String(length=256), nullable=False),
        sa.Column("nickname", sa.String(length=255), nullable=False),
        sa.Column("liked_count", sa.Integer(), nullable=False),
        sa.Column("collected_count", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("share_count", sa.Integer(), nullable=False),
        sa.Column("aweme_url", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=False),
        sa.Column("video_download_url", sa.Text(), nullable=False),
        sa.Column("music_download_url", sa.Text(), nullable=False),
        sa.Column("note_download_url", sa.Text(), nullable=False),
        sa.Column("source_keyword", sa.String(length=512), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "aweme_id", name="uq_douyin_aweme_task_aweme"),
    )
    op.create_index("ix_douyin_aweme_task_id", "douyin_aweme", ["task_id"])
    op.create_index("ix_douyin_aweme_aweme_id", "douyin_aweme", ["aweme_id"])

    op.create_table(
        "douyin_comment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("comment_id", sa.String(length=128), nullable=False),
        sa.Column("aweme_id", sa.String(length=128), nullable=False),
        sa.Column("parent_comment_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("create_time", sa.Integer(), nullable=True),
        sa.Column("creator_hash", sa.String(length=64), nullable=False),
        sa.Column("sec_uid", sa.String(length=256), nullable=False),
        sa.Column("nickname", sa.String(length=255), nullable=False),
        sa.Column("sub_comment_count", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("pictures", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "comment_id", name="uq_douyin_comment_task_comment"
        ),
    )
    op.create_index("ix_douyin_comment_task_id", "douyin_comment", ["task_id"])
    op.create_index("ix_douyin_comment_comment_id", "douyin_comment", ["comment_id"])
    op.create_index("ix_douyin_comment_aweme_id", "douyin_comment", ["aweme_id"])

    op.create_table(
        "douyin_user_action",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("account_hash", sa.String(length=64), nullable=False),
        sa.Column("aweme_id", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "account_hash",
            "aweme_id",
            "action_type",
            name="uq_douyin_action_task_account_aweme_type",
        ),
    )
    op.create_index("ix_douyin_user_action_task_id", "douyin_user_action", ["task_id"])
    op.create_index("ix_douyin_user_action_aweme_id", "douyin_user_action", ["aweme_id"])
    op.create_index("ix_douyin_user_action_action_type", "douyin_user_action", ["action_type"])


def downgrade() -> None:
    op.drop_table("douyin_user_action")
    op.drop_table("douyin_comment")
    op.drop_table("douyin_aweme")
    op.drop_table("crawl_task")

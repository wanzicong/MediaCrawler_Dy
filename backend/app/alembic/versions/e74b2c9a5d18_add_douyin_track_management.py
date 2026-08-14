"""Add Douyin track management and task attribution.

Revision ID: e74b2c9a5d18
Revises: a63f9d2e4b10
Create Date: 2026-08-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e74b2c9a5d18"
down_revision = "a63f9d2e4b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_track",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "normalized_name", name="uq_douyin_track_owner_name"
        ),
    )
    op.create_index("ix_douyin_track_owner_id", "douyin_track", ["owner_id"])
    op.create_index(
        "ix_douyin_track_normalized_name", "douyin_track", ["normalized_name"]
    )
    op.create_index("ix_douyin_track_enabled", "douyin_track", ["enabled"])
    op.create_table(
        "douyin_track_keyword_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["track_id"], ["douyin_track.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["keyword_id"], ["douyin_keyword.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "track_id", "keyword_id", name="uq_douyin_track_keyword_link"
        ),
    )
    op.create_index(
        "ix_douyin_track_keyword_link_track_id",
        "douyin_track_keyword_link",
        ["track_id"],
    )
    op.create_index(
        "ix_douyin_track_keyword_link_keyword_id",
        "douyin_track_keyword_link",
        ["keyword_id"],
    )
    op.create_table(
        "douyin_track_task_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["track_id"], ["douyin_track.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["crawl_task.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "track_id", "task_id", name="uq_douyin_track_task_link"
        ),
    )
    op.create_index(
        "ix_douyin_track_task_link_track_id",
        "douyin_track_task_link",
        ["track_id"],
    )
    op.create_index(
        "ix_douyin_track_task_link_task_id",
        "douyin_track_task_link",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_track_task_link_task_id", table_name="douyin_track_task_link"
    )
    op.drop_index(
        "ix_douyin_track_task_link_track_id", table_name="douyin_track_task_link"
    )
    op.drop_table("douyin_track_task_link")
    op.drop_index(
        "ix_douyin_track_keyword_link_keyword_id",
        table_name="douyin_track_keyword_link",
    )
    op.drop_index(
        "ix_douyin_track_keyword_link_track_id",
        table_name="douyin_track_keyword_link",
    )
    op.drop_table("douyin_track_keyword_link")
    op.drop_index("ix_douyin_track_enabled", table_name="douyin_track")
    op.drop_index("ix_douyin_track_normalized_name", table_name="douyin_track")
    op.drop_index("ix_douyin_track_owner_id", table_name="douyin_track")
    op.drop_table("douyin_track")

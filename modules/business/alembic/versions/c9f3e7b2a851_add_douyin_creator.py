"""Add Douyin creator and creator-task link tables.

Revision ID: c9f3e7b2a851
Revises: 6f2a9d4c81e3
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "c9f3e7b2a851"
down_revision = "6f2a9d4c81e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_creator",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sec_uid", sa.String(length=256), nullable=False),
        sa.Column("creator_hash", sa.String(length=64), nullable=False),
        sa.Column("nickname", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["track_id", "owner_id"],
            ["douyin_track.id", "douyin_track.owner_id"],
            name="fk_douyin_creator_track_owner",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "sec_uid", name="uq_douyin_creator_owner_sec_uid"
        ),
    )
    op.create_index("ix_douyin_creator_owner_id", "douyin_creator", ["owner_id"])
    op.create_index("ix_douyin_creator_track_id", "douyin_creator", ["track_id"])
    op.create_index("ix_douyin_creator_sec_uid", "douyin_creator", ["sec_uid"])
    op.create_index(
        "ix_douyin_creator_creator_hash", "douyin_creator", ["creator_hash"]
    )
    op.create_index("ix_douyin_creator_enabled", "douyin_creator", ["enabled"])

    op.create_table(
        "douyin_creator_task_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["douyin_creator.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id", "task_id", name="uq_douyin_creator_task_link"
        ),
    )
    op.create_index(
        "ix_douyin_creator_task_link_creator_id",
        "douyin_creator_task_link",
        ["creator_id"],
    )
    op.create_index(
        "ix_douyin_creator_task_link_task_id",
        "douyin_creator_task_link",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_table("douyin_creator_task_link")
    op.drop_table("douyin_creator")

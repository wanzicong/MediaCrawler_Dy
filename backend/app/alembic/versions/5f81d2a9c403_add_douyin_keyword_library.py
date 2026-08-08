"""Add the Douyin keyword library and task bindings.

Revision ID: 5f81d2a9c403
Revises: 0bd8ca4f712e
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "5f81d2a9c403"
down_revision = "0bd8ca4f712e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_keyword",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "normalized_keyword", name="uq_douyin_keyword_owner_value"
        ),
    )
    op.create_index("ix_douyin_keyword_owner_id", "douyin_keyword", ["owner_id"])
    op.create_index(
        "ix_douyin_keyword_normalized_keyword",
        "douyin_keyword",
        ["normalized_keyword"],
    )
    op.create_index("ix_douyin_keyword_enabled", "douyin_keyword", ["enabled"])

    op.create_table(
        "douyin_keyword_task_link",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("keyword_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["keyword_id"], ["douyin_keyword.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["crawl_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "keyword_id", "task_id", name="uq_douyin_keyword_task_link"
        ),
    )
    op.create_index(
        "ix_douyin_keyword_task_link_keyword_id",
        "douyin_keyword_task_link",
        ["keyword_id"],
    )
    op.create_index(
        "ix_douyin_keyword_task_link_task_id",
        "douyin_keyword_task_link",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_keyword_task_link_task_id",
        table_name="douyin_keyword_task_link",
    )
    op.drop_index(
        "ix_douyin_keyword_task_link_keyword_id",
        table_name="douyin_keyword_task_link",
    )
    op.drop_table("douyin_keyword_task_link")
    op.drop_index("ix_douyin_keyword_enabled", table_name="douyin_keyword")
    op.drop_index(
        "ix_douyin_keyword_normalized_keyword", table_name="douyin_keyword"
    )
    op.drop_index("ix_douyin_keyword_owner_id", table_name="douyin_keyword")
    op.drop_table("douyin_keyword")

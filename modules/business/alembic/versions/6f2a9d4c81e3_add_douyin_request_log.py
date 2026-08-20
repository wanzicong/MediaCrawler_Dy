"""Add Douyin request log table.

Revision ID: 6f2a9d4c81e3
Revises: 4a7c9e2d1f65
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "6f2a9d4c81e3"
down_revision = "4a7c9e2d1f65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_request_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("query_params", sa.JSON(), nullable=False),
        sa.Column("request_headers", sa.JSON(), nullable=False),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["crawl_task.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_douyin_request_log_owner_id", "douyin_request_log", ["owner_id"])
    op.create_index("ix_douyin_request_log_task_id", "douyin_request_log", ["task_id"])
    op.create_index("ix_douyin_request_log_method", "douyin_request_log", ["method"])
    op.create_index("ix_douyin_request_log_path", "douyin_request_log", ["path"])
    op.create_index(
        "ix_douyin_request_log_response_status", "douyin_request_log", ["response_status"]
    )
    op.create_index(
        "ix_douyin_request_log_owner_created",
        "douyin_request_log",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("douyin_request_log")

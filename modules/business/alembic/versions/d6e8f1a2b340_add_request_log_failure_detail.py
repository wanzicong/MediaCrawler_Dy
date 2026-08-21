"""Add sanitized failure details to Douyin request logs.

Revision ID: d6e8f1a2b340
Revises: f2b9d4a6e810
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

revision = "d6e8f1a2b340"
down_revision = "f2b9d4a6e810"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加仅用于保存脱敏、限长失败返回快照的 JSON 字段。"""
    op.add_column(
        "douyin_request_log",
        sa.Column("failure_detail", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """移除失败返回快照字段。"""
    op.drop_column("douyin_request_log", "failure_detail")

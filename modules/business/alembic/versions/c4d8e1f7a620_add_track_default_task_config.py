"""Add per-track default crawl task configuration.

Revision ID: c4d8e1f7a620
Revises: a7c1e5f29b40
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d8e1f7a620"
down_revision = "a7c1e5f29b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为赛道增加不含敏感信息的默认任务参数 JSON。"""
    op.add_column(
        "douyin_track",
        sa.Column(
            "default_task_config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )


def downgrade() -> None:
    """移除赛道默认任务参数。"""
    op.drop_column("douyin_track", "default_task_config")

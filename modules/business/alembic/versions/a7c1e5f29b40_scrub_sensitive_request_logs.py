"""Scrub sensitive values from existing Douyin request logs.

Revision ID: a7c1e5f29b40
Revises: f5a2b8c7d391
Create Date: 2026-08-20
"""

from alembic import op

revision = "a7c1e5f29b40"
down_revision = "f5a2b8c7d391"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """不可逆地清除历史日志中的 Cookie、签名、令牌和原始账号标识。"""
    op.execute(
        """
        UPDATE douyin_request_log
        SET url = split_part(split_part(url, '?', 1), '#', 1),
            query_params = '{}'::json,
            request_headers = '{}'::json,
            request_body = NULL
        """
    )


def downgrade() -> None:
    """敏感数据清除不可逆，降级时无需恢复。"""

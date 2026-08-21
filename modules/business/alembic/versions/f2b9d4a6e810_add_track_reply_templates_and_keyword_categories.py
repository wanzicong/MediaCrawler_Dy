"""Add track reply templates and keyword categories.

Revision ID: f2b9d4a6e810
Revises: c4d8e1f7a620
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op

revision = "f2b9d4a6e810"
down_revision = "c4d8e1f7a620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加赛道话术/分类 JSON 库，并给关键词增加赛道内分类。"""
    op.add_column(
        "douyin_track",
        sa.Column(
            "reply_templates",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "douyin_track",
        sa.Column(
            "keyword_categories",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "douyin_keyword",
        sa.Column("category", sa.String(length=100), nullable=False, server_default=""),
    )
    op.create_index(
        op.f("ix_douyin_keyword_category"),
        "douyin_keyword",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    """移除关键词分类与赛道话术/分类库。"""
    op.drop_index(op.f("ix_douyin_keyword_category"), table_name="douyin_keyword")
    op.drop_column("douyin_keyword", "category")
    op.drop_column("douyin_track", "keyword_categories")
    op.drop_column("douyin_track", "reply_templates")

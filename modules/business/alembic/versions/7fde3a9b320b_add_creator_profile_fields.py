"""add creator profile fields

Revision ID: 7fde3a9b320b
Revises: c3f1a7d94e58
Create Date: 2026-09-22 22:00:46.153398

给达人表补「主页基础信息」字段：粉丝数、获赞数、主页作品总数、签名、头像、
抖音号、IP 归属地与最近同步时间/失败原因。这些字段由「刷新达人信息」从抖音
主页接口回填，用于达人列表的展示、筛选与排序。
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '7fde3a9b320b'
down_revision = 'c3f1a7d94e58'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "douyin_creator",
        sa.Column("follower_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "douyin_creator",
        sa.Column("total_favorited", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "douyin_creator",
        sa.Column(
            "aweme_total_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "douyin_creator",
        sa.Column(
            "signature",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_creator",
        sa.Column(
            "avatar_url",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_creator",
        sa.Column(
            "unique_id",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_creator",
        sa.Column(
            "ip_location",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_creator",
        sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "douyin_creator",
        sa.Column(
            "profile_error",
            sqlmodel.sql.sqltypes.AutoString(length=500),
            nullable=False,
            server_default="",
        ),
    )


def downgrade():
    for column in (
        "profile_error",
        "profile_synced_at",
        "ip_location",
        "unique_id",
        "avatar_url",
        "signature",
        "aweme_total_count",
        "total_favorited",
        "follower_count",
    ):
        op.drop_column("douyin_creator", column)

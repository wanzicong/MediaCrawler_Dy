"""add account profile fields

Revision ID: 4b81c7d6e2aa
Revises: 3f9c1d2e4a55
Create Date: 2026-09-23 01:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '4b81c7d6e2aa'
down_revision = '3f9c1d2e4a55'
branch_labels = None
depends_on = None


def upgrade():
    """douyin_account 新增本人资料字段：抖音昵称、头像地址、抖音号与同步时间。

    这些字段由「登录 / 验证」时调用本人资料接口回填，用于账号管理页展示；
    均为可空历史兼容的默认空值列，表数量不变。
    """
    op.add_column(
        "douyin_account",
        sa.Column(
            "nickname",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_account",
        sa.Column(
            "avatar_url",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_account",
        sa.Column(
            "douyin_id",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_account",
        sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    """回滚：删除本人资料相关四列。"""
    op.drop_column("douyin_account", "profile_synced_at")
    op.drop_column("douyin_account", "douyin_id")
    op.drop_column("douyin_account", "avatar_url")
    op.drop_column("douyin_account", "nickname")

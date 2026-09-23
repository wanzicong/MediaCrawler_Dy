"""widen creator counters

Revision ID: 5c2a4e77d1b8
Revises: 4b81c7d6e2aa
Create Date: 2026-09-23 01:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5c2a4e77d1b8'
down_revision = '4b81c7d6e2aa'
branch_labels = None
depends_on = None


def upgrade():
    """把达人主页计数列从 INTEGER 放宽为 BIGINT。

    背景：头部账号的「获赞总数」是全部作品点赞之和，远超 INTEGER 上限
    （实测央视新闻 13,730,728,552），同步时抛 NumericValueOutOfRange
    并让整批 100 位达人的事务回滚。粉丝数与主页作品数一并放宽，避免同类问题。
    """
    for column in ("follower_count", "total_favorited", "aweme_total_count"):
        op.alter_column(
            "douyin_creator",
            column,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade():
    """回滚：把三列收回到 INTEGER（超出范围的存量值会被拒绝，需人工处理）。"""
    for column in ("follower_count", "total_favorited", "aweme_total_count"):
        op.alter_column(
            "douyin_creator",
            column,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

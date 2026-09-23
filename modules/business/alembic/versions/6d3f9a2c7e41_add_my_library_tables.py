"""add my library tables

Revision ID: 6d3f9a2c7e41
Revises: 5c2a4e77d1b8
Create Date: 2026-09-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '6d3f9a2c7e41'
down_revision = '5c2a4e77d1b8'
branch_labels = None
depends_on = None


def upgrade():
    """新增「我的」模块两张表：账号关注列表、账号点赞/收藏作品。"""
    op.create_table(
        "douyin_following",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("sec_uid", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=False),
        sa.Column("uid_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("nickname", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("avatar_url", sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("follower_count", sa.BigInteger(), nullable=False),
        sa.Column("aweme_count", sa.BigInteger(), nullable=False),
        sa.Column("is_mutual", sa.Boolean(), nullable=False),
        sa.Column("source_task_id", sa.Uuid(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["douyin_account.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"], ["crawl_task.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "uid_hash", name="uq_douyin_following_account_uid"
        ),
    )
    for column in ("owner_id", "account_id", "uid_hash", "is_mutual", "source_task_id"):
        op.create_index(f"ix_douyin_following_{column}", "douyin_following", [column])
    op.create_table(
        "douyin_account_aweme",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("aweme_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("nickname", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("creator_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("cover_url", sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
        sa.Column("aweme_url", sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
        sa.Column("liked_count", sa.BigInteger(), nullable=False),
        sa.Column("comment_count", sa.BigInteger(), nullable=False),
        sa.Column("collected_count", sa.BigInteger(), nullable=False),
        sa.Column("share_count", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_task_id", sa.Uuid(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["douyin_account.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"], ["crawl_task.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "kind", "aweme_id", name="uq_douyin_account_aweme"
        ),
    )
    for column in (
        "owner_id",
        "account_id",
        "kind",
        "aweme_id",
        "creator_hash",
        "source_task_id",
    ):
        op.create_index(
            f"ix_douyin_account_aweme_{column}", "douyin_account_aweme", [column]
        )


def downgrade():
    """回滚：删除「我的」模块两张表。"""
    op.drop_table("douyin_account_aweme")
    op.drop_table("douyin_following")

"""add content categories

Revision ID: 2e7b1fb89d12
Revises: 7fde3a9b320b
Create Date: 2026-09-22 23:25:28.228687

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '2e7b1fb89d12'
down_revision = '7fde3a9b320b'
branch_labels = None
depends_on = None


def upgrade():
    """新增「内容分类」三张表：分类节点、视频归类、达人归类。"""
    op.create_table(
        "douyin_category",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column(
            "normalized_name",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=False,
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(length=500),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_id", "owner_id"],
            ["douyin_category.id", "douyin_category.owner_id"],
            name="fk_douyin_category_parent_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "owner_id", name="uq_douyin_category_id_owner"),
        sa.UniqueConstraint(
            "owner_id",
            "parent_id",
            "normalized_name",
            name="uq_douyin_category_owner_parent_name",
        ),
    )
    op.create_index("ix_douyin_category_owner_id", "douyin_category", ["owner_id"])
    op.create_index("ix_douyin_category_parent_id", "douyin_category", ["parent_id"])
    op.create_table(
        "douyin_video_category",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "aweme_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["douyin_category.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "aweme_id", "category_id", name="uq_douyin_video_category"
        ),
    )
    op.create_index(
        "ix_douyin_video_category_aweme_id", "douyin_video_category", ["aweme_id"]
    )
    op.create_index(
        "ix_douyin_video_category_category_id",
        "douyin_video_category",
        ["category_id"],
    )
    op.create_index(
        "ix_douyin_video_category_owner_id", "douyin_video_category", ["owner_id"]
    )
    op.create_table(
        "douyin_creator_category",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["douyin_creator.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["douyin_category.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id", "category_id", name="uq_douyin_creator_category"
        ),
    )
    op.create_index(
        "ix_douyin_creator_category_creator_id",
        "douyin_creator_category",
        ["creator_id"],
    )
    op.create_index(
        "ix_douyin_creator_category_category_id",
        "douyin_creator_category",
        ["category_id"],
    )


def downgrade():
    """回滚：先删绑定表再删分类表。"""
    op.drop_table("douyin_creator_category")
    op.drop_table("douyin_video_category")
    op.drop_table("douyin_category")

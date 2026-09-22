"""add local browser instances

Revision ID: 3f9c1d2e4a55
Revises: 2e7b1fb89d12
Create Date: 2026-09-23 00:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '3f9c1d2e4a55'
down_revision = '2e7b1fb89d12'
branch_labels = None
depends_on = None


def upgrade():
    """新增本机浏览器实例表与「账号 ↔ 本机浏览器」多绑定表。"""
    op.create_table(
        "douyin_local_browser",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "label", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False
        ),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "name", name="uq_douyin_local_browser_owner_name"
        ),
        sa.UniqueConstraint(
            "owner_id", "port", name="uq_douyin_local_browser_owner_port"
        ),
    )
    op.create_index(
        "ix_douyin_local_browser_owner_id", "douyin_local_browser", ["owner_id"]
    )
    op.create_index("ix_douyin_local_browser_name", "douyin_local_browser", ["name"])
    op.create_index(
        "ix_douyin_local_browser_enabled", "douyin_local_browser", ["enabled"]
    )
    op.create_table(
        "douyin_account_browser",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "slot_name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["douyin_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "slot_name", name="uq_douyin_account_browser"
        ),
    )
    op.create_index(
        "ix_douyin_account_browser_account_id", "douyin_account_browser", ["account_id"]
    )
    op.create_index(
        "ix_douyin_account_browser_slot_name", "douyin_account_browser", ["slot_name"]
    )


def downgrade():
    """回滚：先删绑定表，再删本机浏览器实例表。"""
    op.drop_table("douyin_account_browser")
    op.drop_table("douyin_local_browser")

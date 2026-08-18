"""Add managed Douyin accounts, pools and crawl shards.

Revision ID: 0bd8ca4f712e
Revises: f47a8c1d9e20
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "0bd8ca4f712e"
down_revision = "f47a8c1d9e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_account",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("browser_mode", sa.String(length=16), nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("remote_slot", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("daily_task_limit", sa.Integer(), nullable=False),
        sa.Column("tasks_today", sa.Integer(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("min_request_interval_seconds", sa.Float(), nullable=False),
        sa.Column("active_leases", sa.Integer(), nullable=False),
        sa.Column("failure_streak", sa.Integer(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "name", name="uq_douyin_account_owner_name"
        ),
        sa.UniqueConstraint(
            "owner_id", "profile_key", name="uq_douyin_account_owner_profile"
        ),
    )
    op.create_index("ix_douyin_account_owner_id", "douyin_account", ["owner_id"])
    op.create_index("ix_douyin_account_name", "douyin_account", ["name"])
    op.create_index(
        "ix_douyin_account_browser_mode", "douyin_account", ["browser_mode"]
    )
    op.create_index(
        "ix_douyin_account_remote_slot", "douyin_account", ["remote_slot"]
    )
    op.create_index("ix_douyin_account_status", "douyin_account", ["status"])
    op.create_index("ix_douyin_account_enabled", "douyin_account", ["enabled"])

    op.create_table(
        "douyin_account_pool",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("max_parallel_accounts", sa.Integer(), nullable=False),
        sa.Column("rotation_cursor", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "name", name="uq_douyin_account_pool_owner_name"
        ),
    )
    op.create_index(
        "ix_douyin_account_pool_owner_id", "douyin_account_pool", ["owner_id"]
    )
    op.create_index("ix_douyin_account_pool_name", "douyin_account_pool", ["name"])
    op.create_index(
        "ix_douyin_account_pool_enabled", "douyin_account_pool", ["enabled"]
    )

    op.create_table(
        "douyin_account_pool_member",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pool_id"], ["douyin_account_pool.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["douyin_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pool_id", "account_id", name="uq_douyin_account_pool_member"
        ),
    )
    op.create_index(
        "ix_douyin_account_pool_member_pool_id",
        "douyin_account_pool_member",
        ["pool_id"],
    )
    op.create_index(
        "ix_douyin_account_pool_member_account_id",
        "douyin_account_pool_member",
        ["account_id"],
    )

    op.add_column("crawl_task", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.add_column(
        "crawl_task", sa.Column("account_pool_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "crawl_task",
        sa.Column(
            "account_strategy",
            sa.String(length=32),
            nullable=False,
            server_default="least_loaded",
        ),
    )
    op.create_foreign_key(
        "fk_crawl_task_account_id",
        "crawl_task",
        "douyin_account",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_crawl_task_account_pool_id",
        "crawl_task",
        "douyin_account_pool",
        ["account_pool_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_crawl_task_account_id", "crawl_task", ["account_id"])
    op.create_index(
        "ix_crawl_task_account_pool_id", "crawl_task", ["account_pool_id"]
    )
    op.alter_column("crawl_task", "account_strategy", server_default=None)

    op.create_table(
        "crawl_task_shard",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("shard_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=False),
        sa.Column("aweme_count", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["crawl_task.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["douyin_account.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "shard_index", name="uq_crawl_task_shard_index"
        ),
    )
    op.create_index("ix_crawl_task_shard_task_id", "crawl_task_shard", ["task_id"])
    op.create_index(
        "ix_crawl_task_shard_account_id", "crawl_task_shard", ["account_id"]
    )
    op.create_index("ix_crawl_task_shard_status", "crawl_task_shard", ["status"])


def downgrade() -> None:
    op.drop_index("ix_crawl_task_shard_status", table_name="crawl_task_shard")
    op.drop_index("ix_crawl_task_shard_account_id", table_name="crawl_task_shard")
    op.drop_index("ix_crawl_task_shard_task_id", table_name="crawl_task_shard")
    op.drop_table("crawl_task_shard")

    op.drop_index("ix_crawl_task_account_pool_id", table_name="crawl_task")
    op.drop_index("ix_crawl_task_account_id", table_name="crawl_task")
    op.drop_constraint(
        "fk_crawl_task_account_pool_id", "crawl_task", type_="foreignkey"
    )
    op.drop_constraint("fk_crawl_task_account_id", "crawl_task", type_="foreignkey")
    op.drop_column("crawl_task", "account_strategy")
    op.drop_column("crawl_task", "account_pool_id")
    op.drop_column("crawl_task", "account_id")

    op.drop_index(
        "ix_douyin_account_pool_member_account_id",
        table_name="douyin_account_pool_member",
    )
    op.drop_index(
        "ix_douyin_account_pool_member_pool_id",
        table_name="douyin_account_pool_member",
    )
    op.drop_table("douyin_account_pool_member")
    op.drop_index("ix_douyin_account_pool_enabled", table_name="douyin_account_pool")
    op.drop_index("ix_douyin_account_pool_name", table_name="douyin_account_pool")
    op.drop_index(
        "ix_douyin_account_pool_owner_id", table_name="douyin_account_pool"
    )
    op.drop_table("douyin_account_pool")
    op.drop_index("ix_douyin_account_enabled", table_name="douyin_account")
    op.drop_index("ix_douyin_account_status", table_name="douyin_account")
    op.drop_index("ix_douyin_account_remote_slot", table_name="douyin_account")
    op.drop_index("ix_douyin_account_browser_mode", table_name="douyin_account")
    op.drop_index("ix_douyin_account_name", table_name="douyin_account")
    op.drop_index("ix_douyin_account_owner_id", table_name="douyin_account")
    op.drop_table("douyin_account")

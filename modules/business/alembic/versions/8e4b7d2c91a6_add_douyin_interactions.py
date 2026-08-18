"""Add durable Douyin interaction tasks.

Revision ID: 8e4b7d2c91a6
Revises: 5f81d2a9c403
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "8e4b7d2c91a6"
down_revision = "5f81d2a9c403"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_interaction",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("account_name", sa.String(length=80), nullable=False),
        sa.Column("aweme_id", sa.String(length=128), nullable=False),
        sa.Column("target_comment_id", sa.String(length=128), nullable=True),
        sa.Column("interaction_type", sa.String(length=32), nullable=False),
        sa.Column("content_encrypted", sa.Text(), nullable=False),
        sa.Column("content_preview", sa.String(length=160), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_confirmation",
        ),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_platform_id", sa.String(length=128), nullable=True),
        sa.Column("human_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["crawl_task.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["douyin_account.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_douyin_interaction_idempotency_key"
        ),
    )
    for column in (
        "owner_id",
        "task_id",
        "account_id",
        "aweme_id",
        "target_comment_id",
        "interaction_type",
        "idempotency_key",
        "status",
        "failure_code",
    ):
        op.create_index(
            f"ix_douyin_interaction_{column}", "douyin_interaction", [column]
        )
    op.alter_column("douyin_interaction", "status", server_default=None)
    op.alter_column("douyin_interaction", "attempt_count", server_default=None)

    op.create_table(
        "douyin_interaction_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("interaction_id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["douyin_interaction.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_douyin_interaction_event_interaction_id",
        "douyin_interaction_event",
        ["interaction_id"],
    )
    op.create_index(
        "ix_douyin_interaction_event_event",
        "douyin_interaction_event",
        ["event"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_interaction_event_event",
        table_name="douyin_interaction_event",
    )
    op.drop_index(
        "ix_douyin_interaction_event_interaction_id",
        table_name="douyin_interaction_event",
    )
    op.drop_table("douyin_interaction_event")
    for column in reversed(
        (
            "owner_id",
            "task_id",
            "account_id",
            "aweme_id",
            "target_comment_id",
            "interaction_type",
            "idempotency_key",
            "status",
            "failure_code",
        )
    ):
        op.drop_index(
            f"ix_douyin_interaction_{column}", table_name="douyin_interaction"
        )
    op.drop_table("douyin_interaction")

"""add batch comment scheduling fields to interactions.

Revision ID: f7a3c9d1b5e2
Revises: d6e8f1a2b340
Create Date: 2026-08-22 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a3c9d1b5e2"
down_revision: str | None = "d6e8f1a2b340"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add batch identity, scheduling and account-pool snapshot fields."""
    op.add_column(
        "douyin_interaction",
        sa.Column("batch_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "douyin_interaction",
        sa.Column("sequence_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "douyin_interaction",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "douyin_interaction",
        sa.Column("account_pool_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_douyin_interaction_batch_id",
        "douyin_interaction",
        ["batch_id"],
    )
    op.create_index(
        "ix_douyin_interaction_account_pool_id",
        "douyin_interaction",
        ["account_pool_id"],
    )
    op.create_foreign_key(
        "fk_douyin_interaction_account_pool_id",
        "douyin_interaction",
        "douyin_account_pool",
        ["account_pool_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove batch comment scheduling fields."""
    op.drop_constraint(
        "fk_douyin_interaction_account_pool_id",
        "douyin_interaction",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_douyin_interaction_account_pool_id", table_name="douyin_interaction"
    )
    op.drop_index("ix_douyin_interaction_batch_id", table_name="douyin_interaction")
    op.drop_column("douyin_interaction", "account_pool_id")
    op.drop_column("douyin_interaction", "scheduled_at")
    op.drop_column("douyin_interaction", "sequence_index")
    op.drop_column("douyin_interaction", "batch_id")

"""Add resumable crawl checkpoint fields.

Revision ID: e18c7a4b92d1
Revises: b73f6a91d204
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "e18c7a4b92d1"
down_revision = "b73f6a91d204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawl_task",
        sa.Column(
            "checkpoint_json", sa.Text(), nullable=False, server_default="{}"
        ),
    )
    op.add_column(
        "crawl_task",
        sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crawl_task",
        sa.Column("last_resumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("crawl_task", "checkpoint_json", server_default=None)
    op.alter_column("crawl_task", "resume_count", server_default=None)


def downgrade() -> None:
    op.drop_column("crawl_task", "last_resumed_at")
    op.drop_column("crawl_task", "resume_count")
    op.drop_column("crawl_task", "checkpoint_json")

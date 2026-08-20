"""Add creator_real_sec_uid to douyin_aweme.

Revision ID: f5a2b8c7d391
Revises: d8e4c1f9a273
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op


revision = "f5a2b8c7d391"
down_revision = "d8e4c1f9a273"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_aweme",
        sa.Column(
            "creator_real_sec_uid",
            sa.String(length=256),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )


def downgrade() -> None:
    op.drop_column("douyin_aweme", "creator_real_sec_uid")

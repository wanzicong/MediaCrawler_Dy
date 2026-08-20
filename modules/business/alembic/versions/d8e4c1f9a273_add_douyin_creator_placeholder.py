"""Add is_placeholder to douyin_creator.

Revision ID: d8e4c1f9a273
Revises: c9f3e7b2a851
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op


revision = "d8e4c1f9a273"
down_revision = "c9f3e7b2a851"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_creator",
        sa.Column(
            "is_placeholder",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_douyin_creator_is_placeholder",
        "douyin_creator",
        ["is_placeholder"],
    )


def downgrade() -> None:
    op.drop_index("ix_douyin_creator_is_placeholder", table_name="douyin_creator")
    op.drop_column("douyin_creator", "is_placeholder")

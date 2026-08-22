"""Add an optional username for account login.

Revision ID: b8e2f6a4c901
Revises: f7a3c9d1b5e2
Create Date: 2026-08-22 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2f6a4c901"
down_revision: str | None = "f7a3c9d1b5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a nullable, globally unique login username."""
    op.add_column(
        "user",
        sa.Column("username", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_user_username", "user", ["username"], unique=True)


def downgrade() -> None:
    """Remove the optional login username."""
    op.drop_index("ix_user_username", table_name="user")
    op.drop_column("user", "username")

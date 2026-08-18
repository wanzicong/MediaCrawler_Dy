"""Add media storage location fields.

Revision ID: b73f6a91d204
Revises: a91d3e7c4b22
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op


revision = "b73f6a91d204"
down_revision = "a91d3e7c4b22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_media_asset",
        sa.Column(
            "storage_backend",
            sa.String(length=32),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column(
            "storage_bucket",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "douyin_media_asset",
        sa.Column("object_key", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_douyin_media_asset_storage_backend",
        "douyin_media_asset",
        ["storage_backend"],
    )
    op.alter_column("douyin_media_asset", "storage_backend", server_default=None)
    op.alter_column("douyin_media_asset", "storage_bucket", server_default=None)
    op.alter_column("douyin_media_asset", "object_key", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_media_asset_storage_backend",
        table_name="douyin_media_asset",
    )
    op.drop_column("douyin_media_asset", "object_key")
    op.drop_column("douyin_media_asset", "storage_bucket")
    op.drop_column("douyin_media_asset", "storage_backend")

"""Add Douyin tag management and aweme bindings.

Revision ID: a63f9d2e4b10
Revises: d21c7a4e9b36
Create Date: 2026-08-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "a63f9d2e4b10"
down_revision = "d21c7a4e9b36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_tag",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "normalized_name", name="uq_douyin_tag_owner_name"
        ),
    )
    op.create_index("ix_douyin_tag_owner_id", "douyin_tag", ["owner_id"])
    op.create_index("ix_douyin_tag_name", "douyin_tag", ["name"])
    op.create_table(
        "douyin_aweme_tag",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aweme_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["aweme_record_id"], ["douyin_aweme.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["douyin_tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "aweme_record_id", "tag_id", name="uq_douyin_aweme_tag_record_tag"
        ),
    )
    op.create_index(
        "ix_douyin_aweme_tag_aweme_record_id",
        "douyin_aweme_tag",
        ["aweme_record_id"],
    )
    op.create_index("ix_douyin_aweme_tag_tag_id", "douyin_aweme_tag", ["tag_id"])


def downgrade() -> None:
    op.drop_index("ix_douyin_aweme_tag_tag_id", table_name="douyin_aweme_tag")
    op.drop_index(
        "ix_douyin_aweme_tag_aweme_record_id", table_name="douyin_aweme_tag"
    )
    op.drop_table("douyin_aweme_tag")
    op.drop_index("ix_douyin_tag_name", table_name="douyin_tag")
    op.drop_index("ix_douyin_tag_owner_id", table_name="douyin_tag")
    op.drop_table("douyin_tag")

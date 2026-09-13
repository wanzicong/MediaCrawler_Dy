"""Rename douyin_account.remote_slot to slot.

账号的浏览器绑定从「仅远程槽位」推广为「按 browser_mode 解析的通用槽位」：
本地账号同样绑定本机槽位（local-1 … local-N）。列名随之从 remote_slot
改为 slot，数据与索引原样迁移，不改语义、不丢绑定。

Revision ID: c3f1a7d94e58
Revises: b8e2f6a4c901
Create Date: 2026-09-13 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f1a7d94e58"
down_revision: str | None = "b8e2f6a4c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "douyin_account"
_OLD_COLUMN = "remote_slot"
_NEW_COLUMN = "slot"
_OLD_INDEX = "ix_douyin_account_remote_slot"
_NEW_INDEX = "ix_douyin_account_slot"


def upgrade() -> None:
    """把绑定列重命名为通用槽位名，并同步重命名其索引。"""
    op.alter_column(
        _TABLE,
        _OLD_COLUMN,
        new_column_name=_NEW_COLUMN,
        existing_type=sa.String(length=64),
        existing_nullable=True,
    )
    op.execute(f"ALTER INDEX {_OLD_INDEX} RENAME TO {_NEW_INDEX}")


def downgrade() -> None:
    """还原为远程专用列名，索引一并还原。"""
    op.execute(f"ALTER INDEX {_NEW_INDEX} RENAME TO {_OLD_INDEX}")
    op.alter_column(
        _TABLE,
        _NEW_COLUMN,
        new_column_name=_OLD_COLUMN,
        existing_type=sa.String(length=64),
        existing_nullable=True,
    )

"""Bind every Douyin keyword and crawl task to exactly one track.

Revision ID: 4a7c9e2d1f65
Revises: 1d4a7e9c2b63
Create Date: 2026-08-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "4a7c9e2d1f65"
down_revision = "1d4a7e9c2b63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_track",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_douyin_track_is_default", "douyin_track", ["is_default"])
    op.create_unique_constraint(
        "uq_douyin_track_id_owner", "douyin_track", ["id", "owner_id"]
    )

    # Reuse a user-created track with the canonical name where possible.
    op.execute(
        """
        UPDATE douyin_track
        SET is_default = TRUE, enabled = TRUE
        WHERE normalized_name = '默认赛道'
        """
    )
    # Deterministic UUIDs make the data migration retry-safe without depending on
    # database extensions such as pgcrypto.
    op.execute(
        """
        INSERT INTO douyin_track (
            id, owner_id, name, normalized_name, description, prompt,
            enabled, is_default, created_at, updated_at
        )
        SELECT
            md5(u.id::text || '-douyin-default-track')::uuid,
            u.id,
            '默认赛道',
            '默认赛道',
            '未选择赛道时，关键词、任务和内容会自动归入这里。',
            '',
            TRUE,
            TRUE,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM "user" AS u
        WHERE NOT EXISTS (
            SELECT 1 FROM douyin_track AS t
            WHERE t.owner_id = u.id AND t.is_default = TRUE
        )
        """
    )
    op.create_index(
        "uq_douyin_track_owner_default",
        "douyin_track",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.add_column(
        "douyin_keyword",
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "crawl_task",
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Preserve the earliest valid historical attribution, then use the owner's
    # fallback track for records that never had a link.
    op.execute(
        """
        UPDATE douyin_keyword AS k
        SET track_id = (
            SELECT l.track_id
            FROM douyin_track_keyword_link AS l
            JOIN douyin_track AS t ON t.id = l.track_id
            WHERE l.keyword_id = k.id AND t.owner_id = k.owner_id
            ORDER BY l.created_at ASC, l.id ASC
            LIMIT 1
        )
        """
    )
    op.execute(
        """
        UPDATE douyin_keyword AS k
        SET track_id = t.id
        FROM douyin_track AS t
        WHERE k.track_id IS NULL
          AND t.owner_id = k.owner_id
          AND t.is_default = TRUE
        """
    )
    op.execute(
        """
        UPDATE crawl_task AS c
        SET track_id = (
            SELECT l.track_id
            FROM douyin_track_task_link AS l
            JOIN douyin_track AS t ON t.id = l.track_id
            WHERE l.task_id = c.id AND t.owner_id = c.owner_id
            ORDER BY l.created_at ASC, l.id ASC
            LIMIT 1
        )
        """
    )
    op.execute(
        """
        UPDATE crawl_task AS c
        SET track_id = t.id
        FROM douyin_track AS t
        WHERE c.track_id IS NULL
          AND t.owner_id = c.owner_id
          AND t.is_default = TRUE
        """
    )
    op.execute(
        """
        DO $$
        DECLARE row_record RECORD;
        BEGIN
            FOR row_record IN SELECT id, track_id, request_json FROM crawl_task LOOP
                BEGIN
                    UPDATE crawl_task
                    SET request_json = (
                        row_record.request_json::jsonb
                        || jsonb_build_object('track_id', row_record.track_id::text)
                    )::text
                    WHERE id = row_record.id
                      AND jsonb_typeof(row_record.request_json::jsonb) = 'object';
                EXCEPTION WHEN invalid_text_representation THEN
                    NULL;
                END;
            END LOOP;
        END $$
        """
    )

    op.alter_column("douyin_keyword", "track_id", nullable=False)
    op.alter_column("crawl_task", "track_id", nullable=False)
    op.create_index("ix_douyin_keyword_track_id", "douyin_keyword", ["track_id"])
    op.create_index("ix_crawl_task_track_id", "crawl_task", ["track_id"])
    op.create_foreign_key(
        "fk_douyin_keyword_track_owner",
        "douyin_keyword",
        "douyin_track",
        ["track_id", "owner_id"],
        ["id", "owner_id"],
        ondelete="NO ACTION",
    )
    op.create_foreign_key(
        "fk_crawl_task_track_owner",
        "crawl_task",
        "douyin_track",
        ["track_id", "owner_id"],
        ["id", "owner_id"],
        ondelete="NO ACTION",
    )

    # Collapse the former many-to-many tables into exact compatibility mirrors.
    op.execute(
        """
        DELETE FROM douyin_track_keyword_link AS l
        USING douyin_keyword AS k
        WHERE l.keyword_id = k.id AND l.track_id <> k.track_id
        """
    )
    op.execute(
        """
        INSERT INTO douyin_track_keyword_link (id, track_id, keyword_id, created_at)
        SELECT md5(k.id::text || '-track-link')::uuid, k.track_id, k.id, CURRENT_TIMESTAMP
        FROM douyin_keyword AS k
        WHERE NOT EXISTS (
            SELECT 1 FROM douyin_track_keyword_link AS l
            WHERE l.keyword_id = k.id
        )
        """
    )
    op.execute(
        """
        DELETE FROM douyin_track_task_link AS l
        USING crawl_task AS c
        WHERE l.task_id = c.id AND l.track_id <> c.track_id
        """
    )
    op.execute(
        """
        INSERT INTO douyin_track_task_link (id, track_id, task_id, created_at)
        SELECT md5(c.id::text || '-track-link')::uuid, c.track_id, c.id, CURRENT_TIMESTAMP
        FROM crawl_task AS c
        WHERE NOT EXISTS (
            SELECT 1 FROM douyin_track_task_link AS l
            WHERE l.task_id = c.id
        )
        """
    )
    op.create_unique_constraint(
        "uq_douyin_track_keyword_single_track",
        "douyin_track_keyword_link",
        ["keyword_id"],
    )
    op.create_unique_constraint(
        "uq_douyin_track_task_single_track",
        "douyin_track_task_link",
        ["task_id"],
    )
    # Abort the upgrade instead of leaving a partially classified catalog if a
    # future legacy data shape escapes the deterministic backfill above.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM "user" AS u
                LEFT JOIN douyin_track AS t
                  ON t.owner_id = u.id AND t.is_default = TRUE
                GROUP BY u.id
                HAVING COUNT(t.id) <> 1
            ) THEN
                RAISE EXCEPTION 'track binding migration: owner default invariant failed';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM douyin_keyword AS k
                JOIN douyin_track AS t ON t.id = k.track_id
                WHERE t.owner_id <> k.owner_id
            ) THEN
                RAISE EXCEPTION 'track binding migration: keyword owner invariant failed';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM crawl_task AS c
                JOIN douyin_track AS t ON t.id = c.track_id
                WHERE t.owner_id <> c.owner_id
            ) THEN
                RAISE EXCEPTION 'track binding migration: task owner invariant failed';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM douyin_keyword AS k
                LEFT JOIN douyin_track_keyword_link AS l ON l.keyword_id = k.id
                GROUP BY k.id, k.track_id
                HAVING COUNT(l.id) <> 1 OR MIN(l.track_id::text) <> k.track_id::text
            ) THEN
                RAISE EXCEPTION 'track binding migration: keyword mirror invariant failed';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM crawl_task AS c
                LEFT JOIN douyin_track_task_link AS l ON l.task_id = c.id
                GROUP BY c.id, c.track_id
                HAVING COUNT(l.id) <> 1 OR MIN(l.track_id::text) <> c.track_id::text
            ) THEN
                RAISE EXCEPTION 'track binding migration: task mirror invariant failed';
            END IF;
        END $$
        """
    )
    op.alter_column("douyin_track", "is_default", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "uq_douyin_track_task_single_track",
        "douyin_track_task_link",
        type_="unique",
    )
    op.drop_constraint(
        "uq_douyin_track_keyword_single_track",
        "douyin_track_keyword_link",
        type_="unique",
    )
    op.drop_constraint("fk_crawl_task_track_owner", "crawl_task", type_="foreignkey")
    op.drop_constraint(
        "fk_douyin_keyword_track_owner", "douyin_keyword", type_="foreignkey"
    )
    op.drop_index("ix_crawl_task_track_id", table_name="crawl_task")
    op.drop_index("ix_douyin_keyword_track_id", table_name="douyin_keyword")
    op.drop_column("crawl_task", "track_id")
    op.drop_column("douyin_keyword", "track_id")
    op.drop_index("uq_douyin_track_owner_default", table_name="douyin_track")
    op.drop_constraint(
        "uq_douyin_track_id_owner", "douyin_track", type_="unique"
    )
    op.drop_index("ix_douyin_track_is_default", table_name="douyin_track")
    op.drop_column("douyin_track", "is_default")

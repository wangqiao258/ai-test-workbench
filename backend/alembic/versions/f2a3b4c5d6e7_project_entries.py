"""project entries replace base url

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-27 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column("entries", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.execute(
        """
        UPDATE project
        SET entries = COALESCE((
            SELECT json_agg(
                json_build_object(
                    'name', '入口-' || ordinality,
                    'url', regexp_replace(btrim(part), '/+$', ''),
                    'note', ''
                )
                ORDER BY ordinality
            )
            FROM unnest(string_to_array(replace(base_url, '，', ','), ','))
                WITH ORDINALITY AS parts(part, ordinality)
            WHERE btrim(part) <> ''
              AND (
                  btrim(part) LIKE 'http://%'
                  OR btrim(part) LIKE 'https://%'
              )
        ), '[]'::json)
        WHERE base_url <> ''
        """
    )
    op.alter_column("project", "entries", server_default=None)
    op.drop_column("project", "base_url")


def downgrade() -> None:
    op.add_column(
        "project",
        sa.Column("base_url", sa.String(length=255), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE project
        SET base_url = COALESCE(entries->0->>'url', '')
        WHERE json_typeof(entries) = 'array' AND json_array_length(entries) > 0
        """
    )
    op.alter_column("project", "base_url", server_default=None)
    op.drop_column("project", "entries")

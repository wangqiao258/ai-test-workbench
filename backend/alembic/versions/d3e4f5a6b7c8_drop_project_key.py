"""drop unused project key

Revision ID: d3e4f5a6b7c8
Revises: c1a2b3d4e5f6
Create Date: 2026-11-25 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("uq_project_key"), "project", type_="unique")
    op.drop_column("project", "key")


def downgrade() -> None:
    op.add_column("project", sa.Column("key", sa.String(length=64), nullable=True))
    op.execute("UPDATE project SET key = replace(id::text, '-', '') WHERE key IS NULL")
    op.alter_column("project", "key", nullable=False)
    op.create_unique_constraint(op.f("uq_project_key"), "project", ["key"])

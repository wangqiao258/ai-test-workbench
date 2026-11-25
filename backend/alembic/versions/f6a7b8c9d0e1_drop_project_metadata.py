"""drop project metadata columns

Revision ID: f6a7b8c9d0e1
Revises: d3e4f5a6b7c8
Create Date: 2026-11-25 11:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("project", "repo")
    op.drop_column("project", "environment")
    op.drop_column("project", "owner")


def downgrade() -> None:
    op.add_column(
        "project",
        sa.Column("repo", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "project",
        sa.Column("environment", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "project",
        sa.Column("owner", sa.String(length=120), nullable=False, server_default=""),
    )
    op.alter_column("project", "repo", server_default=None)
    op.alter_column("project", "environment", server_default=None)
    op.alter_column("project", "owner", server_default=None)

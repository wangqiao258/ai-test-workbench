"""add project base url

Revision ID: b2c3d4e5f6a7
Revises: f6a7b8c9d0e1
Create Date: 2026-11-25 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column("base_url", sa.String(length=255), nullable=False, server_default=""),
    )
    op.alter_column("project", "base_url", server_default=None)


def downgrade() -> None:
    op.drop_column("project", "base_url")

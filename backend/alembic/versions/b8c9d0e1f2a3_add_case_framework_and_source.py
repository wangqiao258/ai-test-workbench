"""add case framework and git source

Revision ID: b8c9d0e1f2a3
Revises: f7a8b9c0d1e2
Create Date: 2026-11-26 21:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_case",
        sa.Column("framework", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "test_case",
        sa.Column("source_repo", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "test_case",
        sa.Column("source_ref", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "test_case",
        sa.Column("source_commit", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "test_case",
        sa.Column("metadata_source", sa.String(length=16), nullable=False, server_default="legacy"),
    )


def downgrade() -> None:
    op.drop_column("test_case", "metadata_source")
    op.drop_column("test_case", "source_commit")
    op.drop_column("test_case", "source_ref")
    op.drop_column("test_case", "source_repo")
    op.drop_column("test_case", "framework")

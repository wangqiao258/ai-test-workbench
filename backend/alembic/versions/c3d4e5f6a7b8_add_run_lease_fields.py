"""add run request lease fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26 00:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_request",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "run_request",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "run_request",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("run_request", "attempt", server_default=None)
    op.create_index(
        "ix_run_request_status_lease",
        "run_request",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_request_status_lease", table_name="run_request")
    op.drop_column("run_request", "lease_expires_at")
    op.drop_column("run_request", "heartbeat_at")
    op.drop_column("run_request", "attempt")

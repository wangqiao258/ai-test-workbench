"""drop run request

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-26 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("run_request")


def downgrade() -> None:
    op.create_table(
        "run_request",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("spec_paths", sa.JSON(), nullable=False),
        sa.Column("case_nodeids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("yaml_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("run_external_id", sa.String(length=128), nullable=True),
        sa.Column("log_path", sa.String(length=512), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name=op.f("ck_run_request_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_run_request_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["app_user.id"],
            name=op.f("fk_run_request_requested_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_request")),
    )
    op.create_index(
        "ix_run_request_project_status",
        "run_request",
        ["project_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_run_request_status_created",
        "run_request",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_run_request_status_lease",
        "run_request",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_run_request_project_id"),
        "run_request",
        ["project_id"],
        unique=False,
    )
    op.alter_column("run_request", "case_nodeids", server_default=None)
    op.alter_column("run_request", "attempt", server_default=None)

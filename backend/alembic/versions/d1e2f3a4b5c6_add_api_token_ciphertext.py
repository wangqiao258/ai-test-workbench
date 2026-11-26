"""add api token ciphertext

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-11-26 23:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_token",
        sa.Column("token_ciphertext", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("api_token", "token_ciphertext")

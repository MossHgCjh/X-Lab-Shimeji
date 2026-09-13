"""add focus end reason

Revision ID: ce902072ba82
Revises: 0002
Create Date: 2026-09-12 20:29:30.961361
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'ce902072ba82'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.add_column(
        "focus_sessions",
        sa.Column("end_reason", sa.String(length=20), nullable=True),
    )


def downgrade():
    op.drop_column("focus_sessions", "end_reason")


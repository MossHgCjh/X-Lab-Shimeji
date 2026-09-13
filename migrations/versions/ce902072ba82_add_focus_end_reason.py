"""Add focus lifecycle state and schedule link."""

import sqlalchemy as sa
from alembic import op

revision = "ce902072ba82"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "focus_sessions",
        sa.Column(
            "end_reason",
            sa.String(length=20),
            nullable=True,
        ),
    )

    op.add_column(
        "focus_sessions",
        sa.Column(
            "schedule_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_focus_sessions_schedule_id",
        "focus_sessions",
        "schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_focus_sessions_schedule_id",
        "focus_sessions",
        ["schedule_id"],
    )


def downgrade():
    op.drop_index(
        "ix_focus_sessions_schedule_id",
        table_name="focus_sessions",
    )

    op.drop_constraint(
        "fk_focus_sessions_schedule_id",
        "focus_sessions",
        type_="foreignkey",
    )

    op.drop_column(
        "focus_sessions",
        "schedule_id",
    )

    op.drop_column(
        "focus_sessions",
        "end_reason",
    )
"""Add schedule folders, schedules, tags and associations."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # schedule_folders: 自定义日程文件夹
    op.create_table(
        "schedule_folders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_index("ix_schedule_folders_user_id", "schedule_folders", ["user_id"])

    # schedules: 日程
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", sa.Uuid(), sa.ForeignKey("schedule_folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_schedules_user_id", "schedules", ["user_id"])
    op.create_index("ix_schedules_folder_id", "schedules", ["folder_id"])
    op.create_index("ix_schedules_starts_at", "schedules", ["starts_at"])

    # schedule_tags: 日程标签
    op.create_table(
        "schedule_tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_index("ix_schedule_tags_user_id", "schedule_tags", ["user_id"])

    # schedule_tag_associations: 日程-标签多对多关联
    op.create_table(
        "schedule_tag_associations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("schedule_id", sa.Uuid(), sa.ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.Uuid(), sa.ForeignKey("schedule_tags.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("schedule_id", "tag_id"),
    )
    op.create_index("ix_schedule_tag_assoc_schedule_id", "schedule_tag_associations", ["schedule_id"])
    op.create_index("ix_schedule_tag_assoc_tag_id", "schedule_tag_associations", ["tag_id"])


def downgrade():
    for table in ("schedule_tag_associations", "schedule_tags", "schedules", "schedule_folders"):
        op.drop_table(table)

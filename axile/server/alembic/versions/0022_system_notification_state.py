"""保存最近一次真实系统告警结果。"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """独立于账户生命周期，删除账户不删除系统告警摘要。"""
    op.create_table(
        "system_notification_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=True),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """移除系统告警摘要，不改变通知配置。"""
    op.drop_table("system_notification_state")

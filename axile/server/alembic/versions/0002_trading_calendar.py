"""增加插件交易日历。

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建基础日历、人工调整与刷新配置表。"""
    op.create_table(
        "trading_calendar",
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("cal_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("calendar_id", "cal_date"),
    )
    op.create_table(
        "trading_calendar_override",
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("cal_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("calendar_id", "cal_date"),
    )
    op.create_table(
        "trading_calendar_config",
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("refresh_kind", sa.Text(), nullable=False),
        sa.Column("function_code", sa.Text(), nullable=False),
        sa.Column("last_sync_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("calendar_id"),
    )


def downgrade() -> None:
    """删除交易日历相关表。"""
    op.drop_table("trading_calendar_config")
    op.drop_table("trading_calendar_override")
    op.drop_table("trading_calendar")

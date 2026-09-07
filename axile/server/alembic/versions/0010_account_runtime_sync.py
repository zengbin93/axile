"""持久化账户运行态 reconcile 的恢复与审计状态.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建账户运行态对齐目标与尝试审计表。"""
    op.create_table(
        "accountruntimesync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reset_worker", sa.Boolean(), nullable=False),
        sa.Column("create_request_key", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.Text(), nullable=False),
        sa.Column("last_attempt_at", sa.Text(), nullable=True),
        sa.Column("synchronized_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_account_runtime_sync_account"),
        sa.UniqueConstraint("create_request_key"),
    )
    op.create_table(
        "accountruntimesyncattempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_runtime_sync_attempt_account", "accountruntimesyncattempt", ["account_id"])


def downgrade() -> None:
    """删除运行态对齐恢复记录。"""
    op.drop_index("ix_account_runtime_sync_attempt_account", table_name="accountruntimesyncattempt")
    op.drop_table("accountruntimesyncattempt")
    op.drop_table("accountruntimesync")

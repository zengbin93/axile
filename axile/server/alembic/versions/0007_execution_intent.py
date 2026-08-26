"""新增执行意图表.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 execution_intent 及部分唯一索引."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "execution_intent" not in inspector.get_table_names():
        op.create_table(
            "execution_intent",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("execution_id", sa.Text(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("trigger_source", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("channel", sa.Text(), nullable=True),
            sa.Column("algorithm", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("started_at", sa.Text(), nullable=True),
            sa.Column("finished_at", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("cancel_requested_at", sa.Text(), nullable=True),
            sa.Column("cancel_reason", sa.Text(), nullable=True),
            sa.Column("terminate_mode", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.create_index("ix_execution_intent_execution_id", "execution_intent", ["execution_id"], unique=True)
    op.create_index(
        "ix_execution_intent_account_id_created_at",
        "execution_intent",
        ["account_id", "created_at"],
        unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_intent_account_queued "
        "ON execution_intent (account_id) WHERE status = 'QUEUED'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_intent_account_running "
        "ON execution_intent (account_id) WHERE status IN ('RUNNING', 'TERMINATING')"
    )


def downgrade() -> None:
    """删除执行意图表."""
    op.execute("DROP INDEX IF EXISTS uq_intent_account_running")
    op.execute("DROP INDEX IF EXISTS uq_intent_account_queued")
    op.drop_index("ix_execution_intent_account_id_created_at", table_name="execution_intent")
    op.drop_index("ix_execution_intent_execution_id", table_name="execution_intent")
    op.drop_table("execution_intent")

"""新增 CTP 品种交易时段快照。

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 CTP 完整快照及其品种时段行。"""
    op.create_table(
        "ctp_session_snapshot",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_ctp_session_snapshot_is_active", "ctp_session_snapshot", ["is_active"])
    op.create_table(
        "ctp_session_snapshot_record",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("exchange_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("segment_no", sa.Integer(), nullable=False),
        sa.Column("time_begin", sa.Text(), nullable=False),
        sa.Column("time_end", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["ctp_session_snapshot.snapshot_id"]),
        sa.PrimaryKeyConstraint("snapshot_id", "exchange_id", "product_id", "segment_no"),
    )


def downgrade() -> None:
    """移除 CTP 品种交易时段快照。"""
    op.drop_table("ctp_session_snapshot_record")
    op.drop_index("ix_ctp_session_snapshot_is_active", table_name="ctp_session_snapshot")
    op.drop_table("ctp_session_snapshot")

"""新增账户资产快照表并回填历史执行快照."""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建快照表并从现有执行记录回填有效账户资产."""
    op.create_table(
        "account_asset_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("assets", sa.JSON(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_asset_snapshot_account_id_id",
        "account_asset_snapshot",
        ["account_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_account_asset_snapshot_account_created",
        "account_asset_snapshot",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_account_asset_snapshot_execution_id",
        "account_asset_snapshot",
        ["execution_id"],
        unique=True,
    )

    bind = op.get_bind()
    records = sa.table(
        "executerecord",
        sa.column("account_id", sa.Integer()),
        sa.column("execution_id", sa.Text()),
        sa.column("raw_result", sa.JSON()),
        sa.column("created_at", sa.Text()),
    )
    snapshots = sa.table(
        "account_asset_snapshot",
        sa.column("account_id", sa.Integer()),
        sa.column("assets", sa.JSON()),
        sa.column("source", sa.Text()),
        sa.column("execution_id", sa.Text()),
        sa.column("created_at", sa.Text()),
    )
    rows = bind.execute(
        sa.select(records.c.account_id, records.c.execution_id, records.c.raw_result, records.c.created_at)
    )
    payloads: list[dict[str, Any]] = []
    for row in rows:
        raw_result = row.raw_result if isinstance(row.raw_result, dict) else {}
        assets = raw_result.get("account_assets")
        if isinstance(assets, dict) and assets:
            payloads.append(
                {
                    "account_id": row.account_id,
                    "assets": assets,
                    "source": "execution",
                    "execution_id": row.execution_id,
                    "created_at": row.created_at,
                }
            )
    if payloads:
        bind.execute(sa.insert(snapshots), payloads)


def downgrade() -> None:
    """移除账户资产快照表."""
    op.drop_index("ix_account_asset_snapshot_execution_id", table_name="account_asset_snapshot")
    op.drop_index("ix_account_asset_snapshot_account_created", table_name="account_asset_snapshot")
    op.drop_index("ix_account_asset_snapshot_account_id_id", table_name="account_asset_snapshot")
    op.drop_table("account_asset_snapshot")

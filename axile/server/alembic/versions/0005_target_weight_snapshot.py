"""新增目标权重计算快照.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建快照表并安全回填可证明的历史账户目标."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "target_weight_snapshot" not in inspector.get_table_names():
        op.create_table(
            "target_weight_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("portfolio_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("raw_weights", sa.JSON(), nullable=True),
            sa.Column("normalized_weights", sa.JSON(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("execution_id", sa.Text(), nullable=True),
            sa.Column("calculated_at", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        _validate_existing_snapshot_table(inspector)
    _ensure_indexes()
    _backfill_account_targets()


def _validate_existing_snapshot_table(inspector: sa.Inspector) -> None:
    """仅接管 SQLModel 已提前创建的完整同构表."""
    required_columns = {
        "id",
        "portfolio_id",
        "account_id",
        "raw_weights",
        "normalized_weights",
        "source",
        "execution_id",
        "calculated_at",
    }
    existing_columns = {column["name"] for column in inspector.get_columns("target_weight_snapshot")}
    missing = sorted(required_columns - existing_columns)
    if missing:
        raise RuntimeError(f"已有 target_weight_snapshot 表结构不完整，缺少列: {', '.join(missing)}")


def _ensure_indexes() -> None:
    """补齐表先于 Alembic 版本创建时可能缺失的索引."""
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes("target_weight_snapshot")}
    indexes = (
        ("ix_target_weight_snapshot_portfolio_id_id", ["portfolio_id", "id"], False),
        ("ix_target_weight_snapshot_account_id_id", ["account_id", "id"], False),
        ("ix_target_weight_snapshot_execution_id", ["execution_id"], True),
    )
    for name, columns, unique in indexes:
        if name not in existing:
            op.create_index(name, "target_weight_snapshot", columns, unique=unique)


def _backfill_account_targets() -> None:
    """从历史调仓输入回填账户口径；无法证明的原始权重保持为空."""
    connection = op.get_bind()
    records = sa.table(
        "executerecord",
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.Integer()),
        sa.column("execution_id", sa.Text()),
        sa.column("raw_input", sa.JSON()),
        sa.column("is_success", sa.Integer()),
        sa.column("created_at", sa.Text()),
    )
    bindings = sa.table(
        "portfolioaccount",
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.Integer()),
        sa.column("portfolio_id", sa.Integer()),
        sa.column("created_at", sa.Text()),
    )
    snapshots = sa.table(
        "target_weight_snapshot",
        sa.column("portfolio_id", sa.Integer()),
        sa.column("account_id", sa.Integer()),
        sa.column("raw_weights", sa.JSON()),
        sa.column("normalized_weights", sa.JSON()),
        sa.column("source", sa.Text()),
        sa.column("execution_id", sa.Text()),
        sa.column("calculated_at", sa.Text()),
    )
    rows = connection.execute(sa.select(records).where(records.c.is_success == 1).order_by(records.c.id.desc()))
    existing_execution_ids = set(
        connection.execute(sa.select(snapshots.c.execution_id).where(snapshots.c.execution_id.is_not(None))).scalars()
    )
    seen_accounts: set[int] = set()
    payloads: list[dict[str, object]] = []
    for row in rows:
        if (
            row.account_id in seen_accounts
            or row.execution_id in existing_execution_ids
            or not isinstance(row.raw_input, dict)
        ):
            continue
        target = row.raw_input.get("curr_target")
        if not isinstance(target, dict):
            continue
        binding = connection.execute(
            sa.select(bindings.c.portfolio_id)
            .where(
                bindings.c.account_id == row.account_id,
                bindings.c.created_at <= row.created_at,
            )
            .order_by(bindings.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if binding is None:
            continue
        seen_accounts.add(row.account_id)
        payloads.append(
            {
                "portfolio_id": binding,
                "account_id": row.account_id,
                "raw_weights": None,
                "normalized_weights": target,
                "source": "execution",
                "execution_id": row.execution_id,
                "calculated_at": row.created_at,
            }
        )
    if payloads:
        connection.execute(sa.insert(snapshots), payloads)


def downgrade() -> None:
    """移除目标权重计算快照."""
    op.drop_index("ix_target_weight_snapshot_execution_id", table_name="target_weight_snapshot")
    op.drop_index("ix_target_weight_snapshot_account_id_id", table_name="target_weight_snapshot")
    op.drop_index("ix_target_weight_snapshot_portfolio_id_id", table_name="target_weight_snapshot")
    op.drop_table("target_weight_snapshot")

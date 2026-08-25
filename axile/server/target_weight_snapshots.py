"""目标权重快照的查询与持久化服务."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, desc, select

from axile.server.db.models import TargetWeightSnapshot, TargetWeightSnapshotPublic


async def append_target_weight_snapshot(
    session: AsyncSession,
    *,
    portfolio_id: int,
    account_id: int | None,
    raw_weights: dict[str, float] | None,
    normalized_weights: dict[str, float] | None,
    source: Literal["manual", "execution"],
    execution_id: str | None = None,
) -> TargetWeightSnapshot:
    """追加并提交一条成功计算快照."""
    snapshot = TargetWeightSnapshot(
        portfolio_id=portfolio_id,
        account_id=account_id,
        raw_weights=raw_weights,
        normalized_weights=normalized_weights,
        source=source,
        execution_id=execution_id,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return snapshot


async def get_latest_portfolio_target_snapshot(
    session: AsyncSession,
    portfolio_id: int,
) -> TargetWeightSnapshot | None:
    """读取组合最近一条具有原始权重的计算快照."""
    return await session.scalar(
        select(TargetWeightSnapshot)
        .where(
            TargetWeightSnapshot.portfolio_id == portfolio_id,
            col(TargetWeightSnapshot.raw_weights).is_not(None),
        )
        .order_by(desc(TargetWeightSnapshot.id))
        .limit(1)
    )


async def get_latest_account_target_snapshot(
    session: AsyncSession,
    account_id: int,
    portfolio_id: int,
) -> TargetWeightSnapshot | None:
    """读取账户在当前组合下最近一条归一化权重快照."""
    return await session.scalar(
        select(TargetWeightSnapshot)
        .where(
            TargetWeightSnapshot.account_id == account_id,
            TargetWeightSnapshot.portfolio_id == portfolio_id,
            col(TargetWeightSnapshot.normalized_weights).is_not(None),
        )
        .order_by(desc(TargetWeightSnapshot.id))
        .limit(1)
    )


def target_snapshot_public(
    snapshot: TargetWeightSnapshot | None,
    *,
    weight_kind: Literal["raw", "normalized"],
) -> TargetWeightSnapshotPublic:
    """把数据库快照转换为稳定的页面响应；无记录时返回未计算态."""
    if snapshot is None:
        return TargetWeightSnapshotPublic()
    weights = snapshot.raw_weights if weight_kind == "raw" else snapshot.normalized_weights
    return TargetWeightSnapshotPublic(
        weights=weights or {},
        calculated_at=snapshot.calculated_at,
        source=snapshot.source,
        execution_id=snapshot.execution_id,
        context_account_id=snapshot.account_id,
    )

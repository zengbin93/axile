"""账户绩效设置和 WBT 收益对比接口，不操作执行与调度."""

from fastapi import APIRouter
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool

from axile.server.api.deps import SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.db.models import ExecuteRecord, PortfolioAccount, TargetWeightSnapshot
from axile.server.db.models.performance import AccountPerformance, PerformanceBinding, PerformanceSettings, RangeKey
from axile.server.performance import calculate_performance, local_time, observation

router = APIRouter()


@router.patch("/performance-settings/{account_id}", response_model=PerformanceSettings)
async def save_performance_settings(
    session: SessionDep, account_id: int, settings: PerformanceSettings
) -> PerformanceSettings:
    """原子更新回测配置，不触发账户调度协调."""
    account = await _get_account_or_404(session, account_id)
    account.backtest_weight_type = settings.backtest_weight_type
    account.backtest_fee_rate = settings.backtest_fee_rate
    session.add(account)
    try:
        await session.commit()
        await session.refresh(account)
    except Exception:
        await session.rollback()
        raise
    return PerformanceSettings.model_validate(account, from_attributes=True)


@router.get("/performance/{account_id}", response_model=AccountPerformance)
async def get_performance(session: SessionDep, account_id: int, range: RangeKey = "all") -> AccountPerformance:
    """完整读取历史，以账户保存的参数生成收益曲线."""
    account = await _get_account_or_404(session, account_id)
    settings = PerformanceSettings.model_validate(account, from_attributes=True)
    records = (
        (await session.execute(select(ExecuteRecord).where(col(ExecuteRecord.account_id) == account_id)))
        .scalars()
        .all()
    )
    snapshots = (
        (await session.execute(select(TargetWeightSnapshot).where(col(TargetWeightSnapshot.account_id) == account_id)))
        .scalars()
        .all()
    )
    fallback = {item.execution_id: item.normalized_weights for item in snapshots if item.execution_id}
    items = [observation(record, fallback.get(record.execution_id or "")) for record in records]
    bindings = (
        (await session.execute(select(PortfolioAccount).where(col(PortfolioAccount.account_id) == account_id)))
        .scalars()
        .all()
    )
    result = await run_in_threadpool(calculate_performance, items, settings, range)
    if result.baseline and result.end:
        start, end = local_time(result.baseline), local_time(result.end)
        result.bindings = [
            PerformanceBinding(time=local_time(binding.created_at).isoformat(), portfolio_id=binding.portfolio_id)
            for binding in sorted(bindings, key=lambda item: local_time(item.created_at))
            if start <= local_time(binding.created_at) <= end
        ]
    return result

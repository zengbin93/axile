"""账户基础管理相关路由."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import ValidationError
from sqlmodel import and_, delete, desc, func, select

from axile.channels import get_channel
from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.models import AccountControlOverride
from axile.server.api.deps import SchedDep, SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.cron import SCHEDULER_TIMEZONE, parse_cron_expr
from axile.server.db.models import (
    Account,
    AccountAssetSnapshot,
    AccountCreate,
    AccountDashboardItemPublic,
    AccountDashboardPublic,
    AccountListPublic,
    AccountNextRunPublic,
    AccountPublic,
    AccountUpdate,
    ExecuteRecord,
    ExecuteRecordListPublic,
    ExecuteRecordPublic,
    Message,
    PortfolioAccount,
    PortfolioAccountListPublic,
    PortfolioAccountPublic,
    now_str,
)
from axile.server.execution.ctp_channels import drop_account_worker, reconcile_china_channel_account
from axile.server.execution.live import live_hub
from axile.server.execution.registry import get_execution_task_state, get_running_execution_id
from axile.server.execution.scheduler import create_job, delete_job
from axile.server.repositories import (
    add_record_portfolio_account,
    get_account_asset_snapshots_before_for_accounts,
    get_earliest_account_asset_snapshots_since_for_accounts,
    get_portfolios_every_account,
    get_recent_account_asset_snapshots_for_accounts,
    get_recent_execute_records_for_accounts,
)
from axile.server.trading_calendar import CalendarDecisionStatus, evaluate_channel_calendar_moment

router = APIRouter()


def _validate_channel_account_config(channel: TradeChannel | str, config: dict[str, object]) -> dict[str, object]:
    """按渠道模型校验账户配置并返回可直接持久化的规范化结果。"""
    plugin = get_channel(str(channel))
    try:
        validated = plugin.account_config_model.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False)
        first = errors[0] if errors else {"loc": (), "msg": "账户配置不合法"}
        location = ".".join(str(part) for part in first.get("loc", ()))
        prefix = f"account_config.{location}" if location else "account_config"
        raise ValueError(f"{prefix}: {first.get('msg', '账户配置不合法')}") from exc
    normalized = cast(
        "dict[str, object]",
        validated.model_dump(mode="json", exclude_none=True, exclude={"channel_type"}),
    )
    for field in plugin.descriptor.account_form.fields:
        condition = field.visible_when
        if condition is not None and normalized.get(condition.field) != condition.equals:
            normalized.pop(field.name, None)
    return normalized


def _account_route_module() -> Any:
    from axile.server.api.routes import account as account_routes

    return account_routes


def _next_job_run_times(job: Any, *, limit: int = 3) -> list[str]:
    """从 APScheduler 任务真源展开未来触发时间.

    Parameters
    ----------
    job : Any
        APScheduler 任务；须提供 ``next_run_time`` 与 ``trigger``。
    limit : int, optional
        最多返回的触发次数。

    Returns
    -------
    list[str]
        按时间升序排列的 ISO8601 时间；暂停或已结束任务返回空列表。
    """
    current = getattr(job, "next_run_time", None)
    trigger = getattr(job, "trigger", None)
    result: list[str] = []
    while current is not None and len(result) < limit:
        encoded = current.isoformat()
        if not result or result[-1] != encoded:
            result.append(encoded)
        if trigger is None:
            break
        current = trigger.get_next_fire_time(current, current)
    return result


def _next_job_execution_times(job: Any, channel: TradeChannel | str, *, limit: int = 3) -> list[str]:
    """按轻量交易日历过滤未来真正会执行的触发时间。"""
    current = getattr(job, "next_run_time", None)
    trigger = getattr(job, "trigger", None)
    if current is None:
        return []

    result: list[str] = []
    first_day = current.astimezone(SCHEDULER_TIMEZONE).date()
    last_day = first_day + timedelta(days=400)
    while current is not None and len(result) < limit:
        local_time = current.astimezone(SCHEDULER_TIMEZONE)
        calendar_day = local_time.date()
        if calendar_day > last_day:
            break
        decision = evaluate_channel_calendar_moment(channel, local_time)
        if decision.status is not CalendarDecisionStatus.AVAILABLE_CLOSED:
            result.append(current.isoformat())
            if trigger is None:
                break
            current = trigger.get_next_fire_time(current, current)
            continue
        if trigger is None:
            break
        next_day = datetime.combine(calendar_day + timedelta(days=1), time.min, tzinfo=SCHEDULER_TIMEZONE)
        current = trigger.get_next_fire_time(current, next_day)
    return result


async def _create_account_record(
    session: SessionDep,
    account: AccountCreate,
    account_config: dict[str, object],
) -> Account:
    """
    创建账户并写入初始组合绑定记录.

    Parameters
    ----------
    session : SessionDep
        当前数据库会话。
    account : AccountCreate
        待创建的账户输入模型。

    Returns
    -------
    Account
        已加入当前会话、并完成初始组合绑定的账户对象。
    """
    db_account = Account.model_validate(account.model_copy(update={"account_config": account_config}))
    session.add(db_account)
    await session.flush()

    account_id = cast("int", db_account.id)
    await add_record_portfolio_account(session, account_id, account.portfolio_id)
    return db_account


def _resolve_next_account_control_binding(
    db_account: Account,
    account: AccountUpdate,
) -> tuple[TradeChannel, str]:
    """
    解析更新后生效的交易渠道与账户控制 preset.

    Parameters
    ----------
    db_account : Account
        当前数据库中的账户对象。
    account : AccountUpdate
        本次更新请求。

    Returns
    -------
    tuple[TradeChannel, str]
        更新后生效的交易渠道与账户控制 preset。
    """
    next_trade_channel = db_account.trade_channel if account.trade_channel is None else account.trade_channel
    next_preset = db_account.account_control_preset
    if account.account_control_preset is not None:
        next_preset = account.account_control_preset
    return next_trade_channel, next_preset


def _build_account_update_data(account: AccountUpdate) -> dict[str, object]:
    """
    将账户更新请求转换为可直接持久化的字段映射.

    Parameters
    ----------
    account : AccountUpdate
        本次更新请求。

    Returns
    -------
    dict[str, object]
        已完成特殊字段规范化的更新载荷。
    """
    data = account.model_dump(exclude_unset=True, mode="json")
    if data.get("portfolio_id") == -1:
        data["portfolio_id"] = None
    if "account_control_override" in data and data["account_control_override"] is not None:
        data["account_control_override"] = AccountControlOverride.model_validate(data["account_control_override"])
    return data


async def _sync_portfolio_binding_update(
    session: SessionDep,
    db_account: Account,
    account_id: int,
    data: dict[str, object],
) -> None:
    """
    根据更新载荷补写账户与组合的绑定历史.

    Parameters
    ----------
    session : SessionDep
        当前数据库会话。
    db_account : Account
        当前数据库中的账户对象。
    account_id : int
        账户 ID。
    data : dict[str, object]
        本次更新对应的持久化字段映射。
    """
    if "portfolio_id" not in data:
        return

    next_portfolio_id = cast("int | None", data["portfolio_id"])
    # 这里必须在 sqlmodel_update 之前比较 old/new，才能准确补写绑定历史。
    if db_account.portfolio_id != next_portfolio_id:
        await add_record_portfolio_account(session, account_id, next_portfolio_id)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=AccountPublic,
)
async def create_account(
    session: SessionDep,
    sched: SchedDep,
    account: AccountCreate,
) -> Account:
    """创建账户."""
    account_routes = _account_route_module()
    try:
        account_routes._validate_account_control_binding(account.trade_channel, account.account_control_preset)
        account_config = _validate_channel_account_config(account.trade_channel, account.account_config)
        cron_expr = parse_cron_expr(account.cron_expr)
        db_account = await _create_account_record(session, account, account_config)
        await session.commit()
        await session.refresh(db_account)
        await create_job(sched, db_account, cron_expr)  # type: ignore[misc]
        await reconcile_china_channel_account(db_account)
    except ValueError as exc:
        await session.rollback()
        logger.exception(f"创建账户失败: {exc}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        logger.exception(f"创建账户失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务器错误: {str(exc)}",
        ) from exc

    return db_account


@router.get("/", response_model=AccountListPublic)
async def list_accounts(session: SessionDep) -> AccountListPublic:
    """获取所有账户列表."""
    accounts = (await session.execute(select(Account))).scalars().all()
    return AccountListPublic(data=[AccountPublic.model_validate(account) for account in accounts])


# 权益迷你线的取数窗口与降采样目标。窗口取近端 N 条资产快照（本账户 ≈ 全历史，活跃账户 ≈ 近数日），
# 让 Hero/舰队卡的迷你线与「回看·绩效」大图（``limit=500`` 全量、点序均匀）同一形状，而非仅
# 最近 20 条那截平尾；再等距降采样到定长，控制 payload 与绘制点数。
_EQUITY_WINDOW = 200
_EQUITY_POINTS = 60


def _downsample_series(values: list[float], target: int) -> list[float]:
    """把权益序列保极值降采样到约 ``target`` 点, 峰谷不丢、含首末端点.

    分桶后每桶取 ``min`` 与 ``max`` 两个极值点、按原始序位先后排列，故每一段的最高/最低
    都不会被抽点跳过（等距抽点会漏掉桶内尖峰）；首末端点强制保真，保证右端与当前权益一致、
    左端为窗口起点。输出点数约为 ``target``（桶内单调或单点时该桶只出一点，故可能略少）。

    Parameters
    ----------
    values : list[float]
        时间正序的权益序列。
    target : int
        目标点数（``>= 4``）。

    Returns
    -------
    list[float]
        约 ``target`` 点的降采样序列；原序列不超过 ``target`` 或 ``target < 4`` 时原样返回。
    """
    n = len(values)
    if n <= target or target < 4:
        return values
    # 预留首末两枚端点，其余交给桶内极值。
    buckets = (target - 2) // 2
    out: list[float] = [values[0]]
    inner = n - 2  # 中段索引 1..n-2
    for b in range(buckets):
        lo = 1 + b * inner // buckets
        hi = 1 + (b + 1) * inner // buckets
        if lo >= hi:
            continue
        i_min = min(range(lo, hi), key=lambda k: values[k])
        i_max = max(range(lo, hi), key=lambda k: values[k])
        # 桶内两极值按序位先后画，单调/单点桶去重后只出一点。
        out.extend(values[k] for k in sorted({i_min, i_max}))
    out.append(values[-1])
    return out


def _safe_total_asset(assets: dict[str, Any]) -> float:
    """从资产快照中容错读取总权益, 非法值回退为 0.0."""
    try:
        return float(assets.get("total_asset") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_valid_total_asset(snapshots: list[AccountAssetSnapshot]) -> float | None:
    """返回快照序列中第一条有效（>0）的总权益；均无则 ``None``。"""
    for snapshot in snapshots:
        total = _safe_total_asset(snapshot.assets)
        if total > 0:
            return total
    return None


def _today_pct_from_baselines(
    current_total: float,
    before_records: list[AccountAssetSnapshot],
    since_records: list[AccountAssetSnapshot],
) -> float | None:
    """
    由已批量取回的基准记录计算「今日」权益涨跌百分比.

    Parameters
    ----------
    current_total : float
        当前权益（取自最近一条有效快照）。
    before_records : list[ExecuteRecord]
        今天 00:00 之前的最近若干条记录（最新在前），用于取「昨收」基准。
    since_records : list[ExecuteRecord]
        今天 00:00 起最早的若干条记录（最早在前），用于取「今开」基准。

    Returns
    -------
    float | None
        今日涨跌百分比；当前权益或基准不可用（≤0）时返回 ``None``。

    Notes
    -----
    与 :func:`_today_pct` 的口径完全一致（昨收优先、退回今开），只是把取数与计算
    拆开，让仪表盘能一次批量取回全部账户的基准记录，消除 N+1。
    """
    if current_total <= 0:
        return None
    baseline = _first_valid_total_asset(before_records)
    if baseline is None:
        baseline = _first_valid_total_asset(since_records)
    if baseline is None or baseline <= 0:
        return None
    return (current_total - baseline) / baseline * 100.0


@router.get("/dashboard", response_model=AccountDashboardPublic)
async def account_dashboard(session: SessionDep, sched: SchedDep) -> AccountDashboardPublic:
    """
    仪表盘聚合: 一次性返回每个账户的舰队卡所需数据.

    Parameters
    ----------
    session : SessionDep
        当前数据库会话。
    sched : SchedDep
        当前调度器实例。

    Returns
    -------
    AccountDashboardPublic
        每个账户一项的聚合列表。

    Notes
    -----
    权益与持仓取自各账户最近一条执行记录的 ``raw_result.account_assets`` 快照，
    ``next_run_time`` 取自 APScheduler；把原本前端对每个账户分别发起的多次请求
    合并为一次，避免舰队页 N 账户 × 数次请求。

    执行记录与今日基准都用窗口函数**批量**取回（每类一次查询，共 3 次），而不是在
    账户循环里逐账户查询——后者是约 3×N 次的 N+1，账户越多查询数线性增长。
    """
    accounts = (await session.execute(select(Account))).scalars().all()
    bindings = await get_portfolios_every_account(session)

    account_ids = [cast("int", account.id) for account in accounts]
    day_start = f"{now_str()[:10]}T00:00:00"
    recent_records_by_account = await get_recent_execute_records_for_accounts(session, account_ids, limit=1)
    recent_by_account = await get_recent_account_asset_snapshots_for_accounts(
        session, account_ids, limit=_EQUITY_WINDOW
    )
    before_by_account = await get_account_asset_snapshots_before_for_accounts(session, account_ids, day_start, limit=5)
    since_by_account = await get_earliest_account_asset_snapshots_since_for_accounts(
        session, account_ids, day_start, limit=5
    )

    items: list[AccountDashboardItemPublic] = []
    for account in accounts:
        account_id = cast("int", account.id)
        recent = recent_by_account.get(account_id, [])
        latest_snapshot = recent[0] if recent else None
        latest_records = recent_records_by_account.get(account_id, [])
        latest = latest_records[0] if latest_records else None
        assets = latest_snapshot.assets if latest_snapshot is not None else {}
        raw_positions = assets.get("positions")
        positions: list[Any] = raw_positions if isinstance(raw_positions, list) else []
        holdings_count = len(positions)
        position_weights = sorted(
            (abs(float(pos.get("market_value") or 0.0)) for pos in positions if isinstance(pos, dict)),
            reverse=True,
        )[:12]
        # 走势跨整个取数窗口、只取有快照的点（避免失败记录插入假的 0），再降采样到定长——
        # 与「回看·绩效」大图同形，而非仅最近 20 条那截平尾。
        equity_full = [_safe_total_asset(snapshot.assets) for snapshot in reversed(recent)]
        equity_series = _downsample_series(equity_full, _EQUITY_POINTS)

        # 「今日」涨跌按自然日锚定（昨收/今开为基准），服务端一处算准，避免前端末两点相减乱跳。
        # 基准记录已在循环外批量取回，这里只做纯计算。
        today_pct = _today_pct_from_baselines(
            _safe_total_asset(assets),
            before_by_account.get(account_id, []),
            since_by_account.get(account_id, []),
        )

        currency = get_channel(account.trade_channel).descriptor.currency

        job = sched.get_job(str(account_id))  # type: ignore[no-untyped-call]
        next_run = getattr(job, "next_run_time", None) if job is not None else None

        # 在途执行快照：以并发锁为「是否在跑」的唯一真源，阶段取自实时中枢。让前端能
        # 看见调度器/他端发起的执行（而非仅本地 runner 猜测）。
        running_execution_id = get_running_execution_id(account_id)
        running_kind: str | None = None
        running_phase: str | None = None
        if running_execution_id is not None:
            task_state = get_execution_task_state(running_execution_id)
            running_kind = task_state.execution_kind.value if task_state is not None else None
            progress = live_hub.progress_for(account_id)
            if progress is not None and progress.get("execution_id") == running_execution_id:
                running_phase = cast("str | None", progress.get("phase"))
            if running_phase is None:
                running_phase = "triggered"

        items.append(
            AccountDashboardItemPublic(
                account_id=account_id,
                name=account.name,
                market=account.market,
                trade_channel=account.trade_channel,
                is_started=account.is_started,
                portfolio_id=bindings.get(account_id),
                is_scheduled=job is not None,
                next_run_time=next_run.isoformat() if next_run is not None else None,
                total_asset=_safe_total_asset(assets),
                currency=str(currency),
                holdings_count=holdings_count,
                position_weights=position_weights,
                equity_series=equity_series,
                asset_observed_at=latest_snapshot.created_at if latest_snapshot is not None else None,
                last_is_success=latest.is_success if latest is not None else None,
                last_exec_at=latest.created_at if latest is not None else None,
                running_execution_id=running_execution_id,
                running_kind=running_kind,
                running_phase=running_phase,
                today_pct=today_pct,
            )
        )

    return AccountDashboardPublic(data=items)


@router.delete("/{account_id}")
async def delete_account(session: SessionDep, sched: SchedDep, account_id: int) -> Message:
    """删除账户."""
    await _get_account_or_404(session, account_id)
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账户不存在")

    await session.delete(account)
    await session.commit()

    delete_job(sched, account_id)
    await drop_account_worker(account_id)
    return Message(message="成功删除账户")


@router.get(
    "/{account_id}",
    response_model=AccountPublic,
)
async def account_info(session: SessionDep, account_id: int) -> Account:
    """获取账户详情."""
    return await _get_account_or_404(session, account_id)


@router.get(
    "/{account_id}/next_run_time",
    response_model=AccountNextRunPublic,
)
async def account_next_run_time(
    session: SessionDep,
    sched: SchedDep,
    account_id: int,
) -> AccountNextRunPublic:
    """
    获取账户未来三次调度执行时间.

    Parameters
    ----------
    session : SessionDep
        当前数据库会话。
    sched : SchedDep
        当前调度器实例。
    account_id : int
        账户 ID。

    Returns
    -------
    AccountNextRunPublic
        账户的调度状态与未来触发时间。

    Raises
    ------
    HTTPException
        账户不存在时抛出 404。

    Notes
    -----
    首次时间直接读取 APScheduler 的 ``next_run_time``，后续时间从同一任务 trigger
    继续展开。
    """
    account = await _get_account_or_404(session, account_id)
    job = sched.get_job(str(account_id))  # type: ignore[no-untyped-call]
    next_run_times = _next_job_run_times(job) if job is not None else []
    next_execution_times = _next_job_execution_times(job, account.trade_channel) if job is not None else []
    return AccountNextRunPublic(
        account_id=account_id,
        is_scheduled=job is not None,
        next_run_time=next_run_times[0] if next_run_times else None,
        next_run_times=next_run_times,
        next_execution_times=next_execution_times,
    )


@router.patch(
    "/{account_id}",
    response_model=AccountPublic,
)
async def update_account(
    session: SessionDep,
    sched: SchedDep,
    account_id: int,
    account: AccountUpdate,
) -> Account:
    """更新账户."""
    db_account = await _get_account_or_404(session, account_id)
    account_routes = _account_route_module()

    try:
        # 账户控制 binding 要按“更新后的目标状态”校验，不能只看当前库里的旧值。
        next_trade_channel, next_preset = _resolve_next_account_control_binding(db_account, account)
        account_routes._validate_account_control_binding(next_trade_channel, next_preset)
        next_account_config = db_account.account_config if account.account_config is None else account.account_config
        normalized_account_config = _validate_channel_account_config(next_trade_channel, next_account_config)

        data = _build_account_update_data(account)
        if account.account_config is not None or account.trade_channel is not None:
            data["account_config"] = normalized_account_config
        runtime_changed = bool({"account_config", "trade_channel", "is_started"} & data.keys())
        await _sync_portfolio_binding_update(session, db_account, account_id, data)
        db_account.sqlmodel_update(data)

        session.add(db_account)
        await session.commit()
        await session.refresh(db_account)
        await account_routes._reconcile_account_job(session, sched, db_account)
        if runtime_changed:
            await reconcile_china_channel_account(db_account, reset=True)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务器错误: {str(exc)}",
        ) from exc

    return db_account


@router.get("/execute_records/{account_id}", response_model=ExecuteRecordListPublic)
async def list_execute_records(
    session: SessionDep,
    account_id: int,
    skip: int = 0,
    limit: int = 100,
) -> ExecuteRecordListPublic:
    """获取账户的执行记录."""
    db_account = await _get_account_or_404(session, account_id)

    count_statement = select(func.count()).select_from(ExecuteRecord).where(ExecuteRecord.account_id == db_account.id)
    count = (await session.execute(count_statement)).scalar_one()

    statement = (
        select(ExecuteRecord)
        .where(ExecuteRecord.account_id == db_account.id)
        # execute_record 没有独立时间排序键时，按自增 id 倒序近似“最新在前”的时间线。
        .order_by(desc(ExecuteRecord.id))
        .offset(skip)
        .limit(limit)
    )
    records = (await session.execute(statement)).scalars().all()

    return ExecuteRecordListPublic(
        data=[ExecuteRecordPublic.model_validate(record) for record in records],
        count=count,
    )


@router.get("/portfolio_records/{account_id}", response_model=PortfolioAccountListPublic)
async def list_portfolio_records(
    session: SessionDep,
    account_id: int,
    skip: int = 0,
    limit: int = 100,
) -> PortfolioAccountListPublic:
    """获取账户的组合更换记录."""
    db_account = await _get_account_or_404(session, account_id)

    count_statement = (
        select(func.count()).select_from(PortfolioAccount).where(PortfolioAccount.account_id == db_account.id)
    )
    count = (await session.execute(count_statement)).scalar_one()

    # 组合绑定记录保持插入顺序返回，便于直接还原账户组合切换历史。
    statement = select(PortfolioAccount).where(PortfolioAccount.account_id == db_account.id).offset(skip).limit(limit)
    records = (await session.execute(statement)).scalars().all()

    return PortfolioAccountListPublic(
        data=[PortfolioAccountPublic.model_validate(record) for record in records],
        count=count,
    )


@router.delete("/execute_records/{account_id}", response_model=Message)
async def delete_execute_records(session: SessionDep, account_id: int) -> Message:
    """删除账户的执行记录."""
    await _get_account_or_404(session, account_id)

    # 执行来源快照属于执行历史的一部分，随记录清理；人工刷新快照保持独立观测语义。
    await session.execute(
        delete(AccountAssetSnapshot).where(
            and_(
                AccountAssetSnapshot.account_id == account_id,
                AccountAssetSnapshot.source == "execution",
            )
        )
    )
    # execution event / artifact 审计流仍不联动。
    stmt = delete(ExecuteRecord).where(and_(ExecuteRecord.account_id == account_id))
    await session.execute(stmt)
    await session.commit()

    return Message(message="成功删除")

"""从执行快照构建两种 WBT 输入与同基准账户收益；渠道日历缺失时降级为不可用。

数量换算后回测使用完整的 ``symbol_results[*].sizing`` 证据（全品种 SIZED 且权重口径），
以 ``target_quantity * unit_notional / equity`` 还原目标敞口，并非实际成交持仓；证据不完整
时整条记录回退到 ``curr_target``。目标权重回测始终使用执行器收到的账户目标。
盯市价与柜台对齐取最新价，无有效最新价回退中间价。
账户与组合优先在同一批参与记录上配对采样：有参与记录的日子取当日最后一条参与记录，
闭市心跳不再单独移动账户日点，从而把差异收敛为纯执行落差；无参与记录的日子保留账户
观察，组合按持仓延续。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
from wbt import WeightBacktest

from axile.server.asset_observations import is_asset_observation
from axile.server.db.models import ExecuteRecord, ExecuteRecordPublic
from axile.server.db.models.performance import (
    AccountPerformance,
    PerformanceCalendar,
    PerformanceCalendarRange,
    PerformanceFallbackRange,
    PerformancePoint,
    PerformanceSettings,
    PerformanceSkips,
    RangeKey,
)
from axile.server.trading_calendar import CalendarDecisionStatus, evaluate_channel_calendar_day

_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _calendar_ranges(days: list[date]) -> list[PerformanceCalendarRange]:
    """把已排序自然日合并为连续闭区间。"""
    if not days:
        return []
    ranges: list[PerformanceCalendarRange] = []
    start = previous = days[0]
    for day in days[1:]:
        if day != previous + timedelta(days=1):
            ranges.append(PerformanceCalendarRange(start=start.isoformat(), end=previous.isoformat()))
            start = day
        previous = day
    ranges.append(PerformanceCalendarRange(start=start.isoformat(), end=previous.isoformat()))
    return ranges


def performance_calendar(channel: str | None, baseline: str | None, end: str | None) -> PerformanceCalendar:
    """构造严格裁剪到绩效结果区间的渠道日历事实。"""
    if channel is None or baseline is None or end is None:
        return PerformanceCalendar(status="unavailable")
    first, last = local_time(baseline).date(), local_time(end).date()
    closed: list[date] = []
    unavailable: list[date] = []
    calendar_id = label = None
    current = first
    try:
        while current <= last:
            # get_channel 对未注册渠道抛 KeyError；这里按缺日历降级而不是上抛。
            decision = evaluate_channel_calendar_day(channel, current)
            calendar_id = decision.calendar_id or calendar_id
            label = decision.label or label
            if decision.status is CalendarDecisionStatus.NOT_REQUIRED:
                return PerformanceCalendar(status="not_required")
            if decision.status is CalendarDecisionStatus.AVAILABLE_CLOSED:
                closed.append(current)
            elif decision.status is CalendarDecisionStatus.UNAVAILABLE:
                unavailable.append(current)
            current += timedelta(days=1)
    except KeyError:
        return PerformanceCalendar(status="unavailable")
    status = (
        "partial"
        if unavailable and len(unavailable) <= (last - first).days
        else "unavailable"
        if unavailable
        else "available"
    )
    return PerformanceCalendar(
        status=status,
        calendar_id=calendar_id,
        label=label,
        closed_ranges=_calendar_ranges(closed),
        unavailable_ranges=_calendar_ranges(unavailable),
    )


@dataclass
class Observation:
    """一条去重后的执行快照，仅包含绩效计算所需数据."""

    id: int
    execution_id: str | None
    time: datetime
    asset: float | None
    target: dict[str, float] | None
    prices: dict[str, float]
    target_weight: dict[str, float] | None = None
    sizing_fallback: bool = False


def local_time(value: str) -> datetime:
    """将有时区和历史无时区时间统一为上海本地时间."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(_TIMEZONE).replace(tzinfo=None)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _mapping(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _mark_price(raw_tick: object) -> float | None:
    """盯市价与柜台对齐取最新价；盘口无效或无最新价回退买卖中间价."""
    tick = _mapping(raw_tick)
    if tick.get("book_valid") is False:
        return None
    last = _number(tick.get("last_price"))
    if last is not None and last > 0:
        return last
    bid, ask = tick.get("bid_price"), tick.get("ask_price")
    bid = _number(bid[0] if isinstance(bid, list) and bid else bid)
    ask = _number(ask[0] if isinstance(ask, list) and ask else ask)
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return None
    return (bid + ask) / 2


def _prices(result: dict[str, object]) -> dict[str, float]:
    raw = result.get("first_ticks", {})
    ticks = dict(_mapping(raw))
    if isinstance(raw, list):
        for value in cast("list[object]", raw):
            tick = _mapping(value)
            symbol = tick.get("symbol")
            if isinstance(symbol, str):
                ticks[symbol] = tick
    for symbol, value in _mapping(result.get("symbol_results")).items():
        item = _mapping(value)
        if item.get("first_tick") is not None:
            ticks[symbol] = item["first_tick"]
    return {
        symbol: price
        for symbol, tick in ticks.items()
        if isinstance(symbol, str) and (price := _mark_price(tick)) is not None
    }


def _target(raw: object) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    target: dict[str, float] = {}
    for symbol, value in _mapping(raw).items():
        weight = _number(value)
        if not isinstance(symbol, str) or not symbol or weight is None:
            return None
        target[symbol] = weight
    return target


def _executable_weight(sizing: dict[str, object]) -> float | None:
    """从单条权重口径换算证据推导可执行权重；证据不完整时返回 None."""
    if str(sizing.get("sizing_mode", "weight")) != "weight" or sizing.get("status") != "SIZED":
        return None
    quantity, notional = _number(sizing.get("target_quantity")), _number(sizing.get("unit_notional"))
    equity = _number(sizing.get("equity"))
    if equity is None or equity <= 0 or quantity is None:
        return None
    if quantity == 0:
        # ZERO_TARGET、不足一手（BELOW_MIN_QUANTITY）或取整到 0：账户真实敞口为零。
        return 0.0
    if notional is None or notional <= 0:
        return None
    return quantity * notional / equity


def _executable_target(result: dict[str, object]) -> dict[str, float] | None:
    """全部品种均有可推导换算证据时返回可执行权重；任一品种证据不足返回 None."""
    results = _mapping(result.get("symbol_results"))
    if not results:
        return None
    target: dict[str, float] = {}
    for symbol, value in results.items():
        weight = _executable_weight(_mapping(_mapping(value).get("sizing")))
        if weight is None or not isinstance(symbol, str) or not symbol:
            return None
        target[symbol] = weight
    return target


def observation(
    record: ExecuteRecord | ExecuteRecordPublic,
    fallback_weights: dict[str, float] | None = None,
) -> Observation:
    """兼容历史行情结构；有换算证据时回放可执行权重，快照仅补缺."""
    result = _mapping(record.raw_result)
    assets = _mapping(result.get("account_assets"))
    asset = _number(assets.get("total_asset"))
    if not is_asset_observation(assets, result):
        asset = None
    target_weight = _target(record.raw_input.get("curr_target"))
    if target_weight is None:
        target_weight = _target(fallback_weights)
    executable = _executable_target(result)
    target = executable if executable is not None else target_weight
    if result.get("execution_kind") == "clear_positions":
        target = target_weight = {}
    return Observation(
        record.id or 0,
        record.execution_id,
        local_time(record.created_at),
        asset,
        target,
        _prices(result),
        target_weight,
        executable is None and target_weight is not None and bool(target_weight),
    )


def _is_baseline(item: Observation) -> bool:
    return (
        item.asset is not None
        and item.asset > 0
        and item.target is not None
        and all(symbol in item.prices for symbol, weight in item.target.items() if weight != 0)
    )


def select_range(items: list[Observation], range_key: RangeKey) -> list[Observation]:
    """相同时刻取最后记录，并选择区间前的共同基准."""
    unique = {item.time: item for item in sorted(items, key=lambda item: (item.time, item.id))}
    ordered = list(unique.values())
    if not ordered:
        return []
    cutoff = ordered[0].time if range_key == "all" else ordered[-1].time - timedelta(days=int(range_key))
    before = [i for i, item in enumerate(ordered) if item.time <= cutoff and _is_baseline(item)]
    after = [i for i, item in enumerate(ordered) if item.time >= cutoff and _is_baseline(item)]
    if before:
        return ordered[before[-1] :]
    if after:
        return ordered[after[0] :]
    # 无共同基准时仍允许显示独立账户曲线。
    return [item for item in ordered if item.time >= cutoff]


def _required_symbols(item: Observation, previous: dict[str, float], target_weight: bool = False) -> set[str] | None:
    """返回参与回测所需的品种集合；目标缺失时返回 None."""
    target = item.target_weight if target_weight else item.target
    if target is None:
        return None
    required = {symbol for symbol, weight in previous.items() if weight != 0}
    required.update(symbol for symbol, weight in target.items() if weight != 0)
    return required


def participating_items(items: list[Observation]) -> list[Observation]:
    """返回可构建回测 bar 的观察序列；参与条件依赖延续中的上一目标."""
    participants: list[Observation] = []
    previous: dict[str, float] = {}
    for item in items:
        required = _required_symbols(item, previous)
        if required is not None and not (required - item.prices.keys()):
            participants.append(item)
            previous = item.target or {}
    return participants


@dataclass
class BacktestInput:
    """WBT 输入与参与统计；未参与观测不产生行，权重自然延续."""

    frame: pd.DataFrame
    used: int
    skips: PerformanceSkips
    backtest_start: datetime | None
    participants: list[Observation]


def build_wbt_input(items: list[Observation], target_weight: bool = False) -> BacktestInput:
    """跳过缺目标或缺盘口的观测；失败执行意味着持仓延续，而非不可恢复的缺口."""
    rows: list[dict[str, object]] = []
    previous: dict[str, float] = {}
    used = 0
    backtest_start: datetime | None = None
    participants: list[Observation] = []
    missing_target = 0
    missing_ticks = 0
    first_time: str | None = None
    last_time: str | None = None
    for item in items:
        target = item.target_weight if target_weight else item.target
        required = _required_symbols(item, previous, target_weight)
        missing = required is not None and bool(required - item.prices.keys())
        if required is None or missing:
            # 跳过：不产生行、不更新延续目标，WBT 按上一已知持仓延续。
            missing_target += target is None
            missing_ticks += target is not None
            first_time = first_time or item.time.isoformat()
            last_time = item.time.isoformat()
            continue
        # 旧仓必须写入显式零权重退出行；其余有报价的零仓也保留供 WBT 建立历史。
        symbols = required | (target.keys() & item.prices.keys())
        rows.extend(
            {"dt": item.time, "symbol": symbol, "weight": target.get(symbol, 0.0), "price": item.prices[symbol]}
            for symbol in sorted(symbols)
        )
        backtest_start = backtest_start or item.time
        previous = target
        used += 1
        participants.append(item)
    skipped = missing_target + missing_ticks
    frame = pd.DataFrame(rows, columns=["dt", "symbol", "weight", "price"])
    return BacktestInput(
        frame=frame.astype({"weight": "float64", "price": "float64"}),
        used=used,
        skips=PerformanceSkips(
            count=skipped,
            missing_target=missing_target,
            missing_ticks=missing_ticks,
            first_time=first_time if skipped else None,
            last_time=last_time if skipped else None,
        ),
        backtest_start=backtest_start,
        participants=participants,
    )


def _portfolio_daily(frame: pd.DataFrame, settings: PerformanceSettings) -> dict[str, float]:
    if frame.empty:
        return {}
    engine = WeightBacktest(
        frame,
        digits=8,
        fee_rate=settings.backtest_fee_rate,
        weight_type=settings.backtest_weight_type,
        n_jobs=1,
    )
    return {str(row["date"])[:10]: float(row["total"]) for row in engine.daily_return.to_dict("records")}


def _merge_daily(
    items: list[Observation],
    daily: dict[str, float] | None,
    backtest_start: datetime | None,
    participants: list[Observation] | None = None,
    target_daily: dict[str, float] | None = None,
    target_start: datetime | None = None,
    fallback_days: set[str] | None = None,
) -> list[PerformancePoint]:
    base = next((item for item in items if item.asset is not None and item.asset > 0), None)
    if base is None or base.asset is None:
        return []
    # 账户与组合优先在同一批参与记录上配对采样；无参与记录的日子保留账户观察，
    # 组合按持仓延续，闭市心跳不会单独移动账户日点。
    by_day: dict[str, Observation] = {}
    for item in items:
        if item.time >= base.time:
            by_day[item.time.date().isoformat()] = item
    for item in participants or ():
        if item.time >= base.time:
            by_day[item.time.date().isoformat()] = item
    nav = 1.0
    target_nav = 1.0
    previous_asset = base.asset
    points: list[PerformancePoint] = []
    # 回测首个参与观测之前组合收益未知；其后无 WBT 条目的日子按持仓延续计 0.
    backtest_day = backtest_start.date().isoformat() if backtest_start is not None else None
    target_day = target_start.date().isoformat() if target_start is not None else None
    for day, last in by_day.items():
        # 日末资产缺失时不拿更早资产伪装同日末值；次日累计仍可由共同基准恢复。
        account = last.asset / base.asset - 1 if last.asset is not None else None
        account_daily = (
            last.asset / previous_asset - 1
            if last.asset is not None and previous_asset is not None and previous_asset > 0
            else None
        )
        previous_asset = last.asset
        portfolio_daily = (
            daily.get(day, 0.0) if daily is not None and backtest_day is not None and day >= backtest_day else None
        )
        if portfolio_daily is not None:
            nav *= 1 + portfolio_daily
        portfolio = nav - 1 if portfolio_daily is not None else None
        target_portfolio_daily = (
            target_daily.get(day, 0.0)
            if target_daily is not None and target_day is not None and day >= target_day
            else None
        )
        if target_portfolio_daily is not None:
            target_nav *= 1 + target_portfolio_daily
        points.append(
            PerformancePoint(
                date=day,
                observed_at=last.time.isoformat(),
                record_id=last.id,
                execution_id=last.execution_id,
                account_return=account,
                account_equity=last.asset,
                portfolio_return=portfolio,
                account_daily_return=account_daily,
                portfolio_daily_return=portfolio_daily,
                target_portfolio_return=target_nav - 1 if target_portfolio_daily is not None else None,
                target_portfolio_daily_return=target_portfolio_daily,
                sizing_fallback=day in (fallback_days or set()),
                difference=account - portfolio if account is not None and portfolio is not None else None,
            )
        )
    # 独立基准点保留执行时间，以便基准当天仍有后续执行时不覆盖日末收益。
    from_backtest = daily is not None and backtest_start is not None and backtest_start <= base.time
    points.insert(
        0,
        PerformancePoint(
            date=base.time.isoformat(),
            observed_at=base.time.isoformat(),
            record_id=base.id,
            execution_id=base.execution_id,
            account_return=0.0,
            account_equity=base.asset,
            portfolio_return=0.0 if from_backtest else None,
            target_portfolio_return=0.0
            if target_daily is not None and target_start is not None and target_start <= base.time
            else None,
            difference=0.0 if from_backtest else None,
        ),
    )
    return points


def _point_fields(point: PerformancePoint | dict[str, object]) -> tuple[str, float | None]:
    if isinstance(point, dict):
        date = str(point.get("date") or "")
        raw = point.get("account_equity")
    else:
        date = point.date
        raw = point.account_equity
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return date, None
    value = float(raw)
    return date, value if math.isfinite(value) and value > 0 else None


def close_before(points: list[PerformancePoint] | list[dict[str, object]], day: str) -> float | None:
    """``day`` 之前最近一日末权益；没有更早日则用基准点。"""
    last_before = None
    baseline = None
    for point in points:
        date, equity = _point_fields(point)
        if equity is None:
            continue
        # 日点 date 是日历日；基准点 date 是完整时间，见 _merge_daily。
        if "T" in date:
            baseline = equity
            continue
        if date < day:
            last_before = equity
    return last_before if last_before is not None else baseline


def calculate_performance(
    observations: list[Observation],
    settings: PerformanceSettings,
    range_key: RangeKey,
    include_backtest: bool = True,
    trade_channel: str | None = None,
) -> AccountPerformance:
    """使用 WBT 原生费后日收益与资产比值生成收益对比."""
    items = select_range(observations, range_key)
    result = AccountPerformance(
        settings=settings,
        backtest_included=include_backtest,
        engine_version=version("wbt"),
        range=range_key,
        record_count=len(observations),
        calendar=PerformanceCalendar(status="unavailable"),
    )
    if not items:
        return result
    result.observation_count = len(items)
    daily = None
    backtest_start: datetime | None = None
    participants: list[Observation] | None = None
    target_daily: dict[str, float] | None = None
    target_start: datetime | None = None
    fallback_days: set[str] = set()
    if include_backtest:
        built = build_wbt_input(items)
        target_built = build_wbt_input(items, target_weight=True)
        result.used_record_count = built.used
        result.target_used_record_count = target_built.used
        result.skips = built.skips
        result.target_skips = target_built.skips
        backtest_start = built.backtest_start
        target_start = target_built.backtest_start
        # 全零目标可参与且无需报价；此时空帧表示现金持仓，收益为零。
        daily = ({} if built.used else None) if built.frame.empty else _portfolio_daily(built.frame, settings)
        target_daily = (
            ({} if target_built.used else None)
            if target_built.frame.empty
            else _portfolio_daily(target_built.frame, settings)
        )
        participants = built.participants or None
        fallback_days = {item.time.date().isoformat() for item in built.participants if item.sizing_fallback}
        result.sizing_fallback_count = sum(item.sizing_fallback for item in built.participants)
        current: PerformanceFallbackRange | None = None
        for item in built.participants:
            if item.sizing_fallback:
                when = item.time.isoformat()
                if current is None:
                    current = PerformanceFallbackRange(start=when, end=when, count=0)
                    result.sizing_fallback_ranges.append(current)
                current.end = when
                current.count += 1
            else:
                current = None
    else:
        # 快速路径用同一参与谓词配对采样，不构建也不运行回测。
        participants = participating_items(items) or None
    result.points = _merge_daily(items, daily, backtest_start, participants, target_daily, target_start, fallback_days)
    result.baseline = result.points[0].date if result.points else None
    result.end = items[-1].time.isoformat()
    result.invalid_asset_count = sum(item.asset is None for item in items)
    result.calendar = performance_calendar(trade_channel, result.baseline, result.end)
    return result

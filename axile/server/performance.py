"""从执行快照构建 WBT 输入与同基准账户收益，不访问交易渠道."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
from wbt import WeightBacktest

from axile.server.db.models import ExecuteRecord, ExecuteRecordPublic
from axile.server.db.models.performance import (
    AccountPerformance,
    PerformanceGap,
    PerformancePoint,
    PerformanceSettings,
    RangeKey,
)

_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass
class Observation:
    """一条去重后的执行快照，仅包含绩效计算所需数据."""

    id: int
    execution_id: str | None
    time: datetime
    asset: float | None
    target: dict[str, float] | None
    prices: dict[str, float]


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


def _mid_price(raw_tick: object) -> float | None:
    tick = _mapping(raw_tick)
    if tick.get("book_valid") is False:
        return None
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
        if isinstance(symbol, str) and (price := _mid_price(tick)) is not None
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


def observation(
    record: ExecuteRecord | ExecuteRecordPublic,
    fallback_weights: dict[str, float] | None = None,
) -> Observation:
    """兼容历史行情结构；仅用相同执行 ID 的目标快照补缺."""
    result = _mapping(record.raw_result)
    assets = _mapping(result.get("account_assets"))
    asset = _number(assets.get("total_asset"))
    if assets.get("source") in ("assumed", "error", "unavailable"):
        asset = None
    target = _target(record.raw_input.get("curr_target", fallback_weights))
    if result.get("execution_kind") == "clear_positions":
        target = {}
    return Observation(
        record.id or 0, record.execution_id, local_time(record.created_at), asset, target, _prices(result)
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


def build_wbt_input(items: list[Observation]) -> tuple[pd.DataFrame, PerformanceGap | None, int]:
    """构建可信前缀；未知区间不能通过后续行情恢复累计收益."""
    rows: list[dict[str, object]] = []
    previous: dict[str, float] = {}
    used = 0
    gap = None
    for item in items:
        target = item.target
        required = {symbol for symbol, weight in previous.items() if weight != 0}
        if target is not None:
            required.update(symbol for symbol, weight in target.items() if weight != 0)
        missing = sorted(required - item.prices.keys())
        if target is None or missing:
            gap = PerformanceGap(
                time=item.time.isoformat(),
                execution_id=item.execution_id,
                reason="目标权重缺失或无效" if target is None else "必要标的缺少有效首笔盘口",
                symbols=missing,
            )
            break
        # 旧仓必须写入显式零权重退出行；其余有报价的零仓也保留供 WBT 建立历史。
        symbols = required | (target.keys() & item.prices.keys())
        rows.extend(
            {"dt": item.time, "symbol": symbol, "weight": target.get(symbol, 0.0), "price": item.prices[symbol]}
            for symbol in sorted(symbols)
        )
        previous = target
        used += 1
    frame = pd.DataFrame(rows, columns=["dt", "symbol", "weight", "price"])
    return frame.astype({"weight": "float64", "price": "float64"}), gap, used


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
    gap: PerformanceGap | None,
) -> list[PerformancePoint]:
    base = next((item for item in items if item.asset is not None and item.asset > 0), None)
    if base is None or base.asset is None:
        return []
    by_day: dict[str, Observation] = {}
    for item in items:
        if item.time >= base.time:
            by_day[item.time.date().isoformat()] = item
    nav = 1.0
    previous_asset = base.asset
    points: list[PerformancePoint] = []
    gap_day = gap.time[:10] if gap else None
    for day, last in by_day.items():
        # 日末资产缺失时不拿更早资产伪装同日末值；次日累计仍可由共同基准恢复。
        account = last.asset / base.asset - 1 if last.asset is not None else None
        account_daily = (
            last.asset / previous_asset - 1
            if last.asset is not None and previous_asset is not None and previous_asset > 0
            else None
        )
        previous_asset = last.asset
        portfolio_daily = daily.get(day, 0.0) if daily is not None and (gap_day is None or day < gap_day) else None
        if portfolio_daily is not None:
            nav *= 1 + portfolio_daily
        portfolio = nav - 1 if portfolio_daily is not None else None
        points.append(
            PerformancePoint(
                date=day,
                observed_at=last.time.isoformat(),
                account_return=account,
                portfolio_return=portfolio,
                account_daily_return=account_daily,
                portfolio_daily_return=portfolio_daily,
                difference=account - portfolio if account is not None and portfolio is not None else None,
            )
        )
    # 独立基准点保留执行时间，以便基准当天仍有后续执行时不覆盖日末收益。
    points.insert(
        0,
        PerformancePoint(
            date=base.time.isoformat(),
            observed_at=base.time.isoformat(),
            account_return=0.0,
            portfolio_return=0.0 if daily is not None and _is_baseline(base) else None,
            difference=0.0 if daily is not None and _is_baseline(base) else None,
        ),
    )
    return points


def calculate_performance(
    observations: list[Observation],
    settings: PerformanceSettings,
    range_key: RangeKey,
    include_backtest: bool = True,
) -> AccountPerformance:
    """使用 WBT 原生费后日收益与资产比值生成收益对比."""
    items = select_range(observations, range_key)
    result = AccountPerformance(
        settings=settings,
        backtest_included=include_backtest,
        engine_version=version("wbt"),
        range=range_key,
        record_count=len(observations),
    )
    if not items:
        return result
    result.observation_count = len(items)
    daily = None
    if include_backtest:
        frame, result.gap, result.used_record_count = build_wbt_input(items)
        daily = _portfolio_daily(frame, settings)
    result.points = _merge_daily(items, daily, result.gap)
    result.baseline = result.points[0].date if result.points else None
    result.end = items[-1].time.isoformat()
    result.invalid_asset_count = sum(item.asset is None for item in items)
    return result

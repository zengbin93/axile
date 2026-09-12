"""期货渠道共享的开平意图翻译与今昨仓拆分。"""

import math

from axile.executor.models.unified_account_assets import PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection


def is_close_intent(direction: OrderDirection, position_side: object) -> bool:
    """仅反向买卖表示平掉指定持仓侧；同向买卖表示开仓。"""
    if position_side not in (None, "LONG", "SHORT"):
        raise ValueError(f"不支持的 position_side: {position_side}")
    return (direction == OrderDirection.SELL and position_side == "LONG") or (
        direction == OrderDirection.BUY and position_side == "SHORT"
    )


def plan_futures_close_orders(
    symbol: str,
    direction: OrderDirection,
    volume: float,
    account_assets: UnifiedAccountAssets,
    exchange: str,
) -> list[tuple[float, dict[str, object]]]:
    """上期所、能源中心按先昨后今拆单，其他交易所使用普通平仓。"""
    if exchange not in ("SHFE", "INE"):
        return [(volume, {"offset_flag": "close"})]
    side = PositionDirection.LONG if direction == OrderDirection.SELL else PositionDirection.SHORT
    prefix = "long" if side == PositionDirection.LONG else "short"
    yesterday = available = 0.0
    for position in account_assets.positions:
        if position.symbol != symbol or position.direction != side or position.volume <= 0:
            continue
        td = float(position.extra.get(f"{prefix}_td", float("nan")))
        yd = float(position.extra.get(f"{prefix}_yd", float("nan")))
        if not all(math.isfinite(v) and v >= 0 for v in (td, yd)) or not math.isclose(
            td + yd, position.volume, rel_tol=0.0, abs_tol=1e-6
        ):
            raise ValueError(f"{symbol}: 今昨仓明细缺失或不一致，拒绝猜测平仓标志")
        # 统一快照只有总冻结量，无法确定冻结的是今仓还是昨仓。
        if position.available_volume < position.volume:
            raise ValueError(f"{symbol}: 持仓存在冻结量，无法安全分配今昨平仓")
        yesterday += yd
        available += position.available_volume
    if volume > available:
        raise ValueError(f"{symbol}: 平仓量超过可用持仓")
    close_yesterday = min(volume, yesterday)
    close_today = volume - close_yesterday
    return [
        (quantity, {"offset_flag": offset})
        for quantity, offset in ((close_yesterday, "close_yesterday"), (close_today, "close_today"))
        if quantity > 0
    ]


def single_close_offset(plan: list[tuple[float, dict[str, object]]]) -> str:
    """单笔接口不能表达混合今昨仓；要求调用方通过分单接口提交。"""
    if len(plan) != 1:
        raise ValueError("平仓涉及今昨两类持仓，请先调用 plan_close_orders 拆单")
    return str(plan[0][1]["offset_flag"])

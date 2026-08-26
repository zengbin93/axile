"""账户在位性：可执行数量相对目标的偏离.

有渠道量化钩子时，待调整 = 现持净仓 ≠ 量化后的目标数量。
没有钩子时仍用权重 0.5 个百分点阈值，避免未装备渠道的仪表盘突然变未知。
合约身份由渠道 ``canonicalize_symbol`` 处理，本模块不写郑商所特例。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from axile.channels.contracts import CanonicalizeSymbol, QuantizeTargetQuantity

# 无数量口径时的权重回退；与前端 ``rebalancePlan`` 在 ``quantities`` 缺失时一致。
REBALANCE_THRESHOLD = 0.5
_ZERO = 1e-6
_QTY_EPS = 1e-9


def _identity_symbol(symbol: str) -> str:
    return symbol


def _to_float(value: object) -> float:
    """把任意标量安全转为浮点数；无法转换时返回 0."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _is_short(direction: object) -> bool:
    """判断持仓方向是否为空头（兼容中英文写法）."""
    if not isinstance(direction, str):
        return False
    return "空" in direction or "short" in direction.lower()


def _round2(value: float) -> float:
    """与 JS ``Number.prototype.toFixed(2)`` 对齐的两位小数."""
    return float(f"{value:.2f}")


def _signed_lots(row: Mapping[str, object]) -> float | None:
    """净仓手数；``extra.net_position`` 优先，否则带符号 ``volume``."""
    extra = row.get("extra")
    if isinstance(extra, dict) and extra.get("net_position") is not None:
        return _to_float(extra.get("net_position"))
    if row.get("volume") is None:
        return None
    mag = abs(_to_float(row.get("volume")))
    return -mag if _is_short(row.get("direction")) else mag


@dataclass(frozen=True, slots=True)
class ExecutableTarget:
    """账户口径下、已对齐持仓代码的可执行目标."""

    weights: dict[str, float]
    quantities: dict[str, float] | None
    off_symbol_count: int


def count_off_symbols(
    positions: list[object],
    target: Mapping[str, float],
    equity: float,
) -> int:
    """
    按权重残差统计待调整品种数（无数量口径时的回退）.

    Parameters
    ----------
    positions : list[object]
        账户快照持仓列表，元素为含 ``symbol`` / ``market_value`` / ``direction`` 的字典。
    target : Mapping[str, float]
        账户口径目标权重（分数，可负=做空）。
    equity : float
        账户总权益，作为归一分母；``<= 0`` 时当前权重按 0 处理。

    Returns
    -------
    int
        待调整品种数；当前与目标都接近 0 的品种不计。
    """
    cur_mv: dict[str, float] = {}
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        mag = abs(_to_float(row.get("market_value")))
        signed = -mag if _is_short(row.get("direction")) else mag
        cur_mv[symbol] = cur_mv.get(symbol, 0.0) + signed
    return _count_off_by_weight(cur_mv, target, equity)


def _count_off_by_weight(cur_mv: Mapping[str, float], target: Mapping[str, float], equity: float) -> int:
    symbols = set(cur_mv) | {key for key in target if isinstance(key, str) and key}
    base = equity if equity > 0 else 0.0
    off = 0
    for symbol in symbols:
        cur = ((cur_mv.get(symbol, 0.0) / base) * 100.0) if base > 0 else 0.0
        tgt = float(target.get(symbol, 0.0) or 0.0) * 100.0
        if abs(cur) < _ZERO and abs(tgt) < _ZERO:
            continue
        if abs(_round2(cur - tgt)) > REBALANCE_THRESHOLD:
            off += 1
    return off


def plan_executable_target(
    positions: list[object],
    target: Mapping[str, float],
    equity: float,
    *,
    canonicalize_symbol: CanonicalizeSymbol = _identity_symbol,
    quantize_target_quantity: QuantizeTargetQuantity | None = None,
) -> ExecutableTarget:
    """
    把持仓与目标收到渠道原生代码，并按可下单数量判定偏离.

    Parameters
    ----------
    positions : list[object]
        账户快照持仓。
    target : Mapping[str, float]
        账户口径目标权重。
    equity : float
        账户总权益。
    canonicalize_symbol : CanonicalizeSymbol, optional
        合约身份归一；缺省恒等。
    quantize_target_quantity : QuantizeTargetQuantity | None, optional
        权重→数量。``None`` 时不下发 quantities，off 回退权重阈值。

    Returns
    -------
    ExecutableTarget
        ``weights`` 已是持仓代码空间；有量化钩子时带 ``quantities``。
    """
    cur_lots: dict[str, float] = {}
    cur_mv: dict[str, float] = {}
    notional_per_unit: dict[str, float] = {}
    has_book: dict[str, bool] = {}

    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        native = canonicalize_symbol(symbol)
        mag = abs(_to_float(row.get("market_value")))
        signed_mv = -mag if _is_short(row.get("direction")) else mag
        cur_mv[native] = cur_mv.get(native, 0.0) + signed_mv
        lots = _signed_lots(row)
        if lots is not None:
            cur_lots[native] = cur_lots.get(native, 0.0) + lots
        volume = abs(_to_float(row.get("volume")))
        if volume > 0 and mag > 0:
            notional_per_unit[native] = mag / volume
        if lots is not None or mag > 0:
            has_book[native] = True

    weights: dict[str, float] = {}
    for key, value in target.items():
        if not isinstance(key, str) or not key:
            continue
        weights[canonicalize_symbol(key)] = float(value or 0.0)

    if quantize_target_quantity is None:
        return ExecutableTarget(
            weights=weights,
            quantities=None,
            off_symbol_count=_count_off_by_weight(cur_mv, weights, equity),
        )

    quantities: dict[str, float] = {}
    off = 0
    symbols = set(weights) | set(cur_lots) | set(cur_mv)
    for symbol in symbols:
        weight = weights.get(symbol, 0.0)
        current = cur_lots.get(symbol)
        booked = has_book.get(symbol, False)
        if abs(weight) < _ZERO and current is None and not booked:
            continue
        if abs(weight) < _ZERO:
            target_qty = 0.0
            quantities[symbol] = 0.0
        elif symbol in notional_per_unit:
            target_qty = float(quantize_target_quantity(weight, equity, notional_per_unit[symbol]))
            quantities[symbol] = target_qty
        else:
            off += 1
            continue
        if current is None:
            if booked or abs(target_qty) > _QTY_EPS:
                off += 1
            continue
        if abs(current - target_qty) > _QTY_EPS:
            off += 1
    return ExecutableTarget(weights=weights, quantities=quantities, off_symbol_count=off)


__all__ = [
    "REBALANCE_THRESHOLD",
    "ExecutableTarget",
    "count_off_symbols",
    "plan_executable_target",
]

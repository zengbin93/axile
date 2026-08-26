"""账户在位性：持仓相对目标的偏离计数.

口径与前端 ``rebalancePlan`` 对齐（``axile/ui/src/lib/derive.ts``）：
带符号市值 / 权益 × 100，绝对值差大于 ``REBALANCE_THRESHOLD`` 个百分点视为待调整。
两边阈值必须保持同一数值，否则舰队头条与详情卡会各说各的。
"""

from __future__ import annotations

from collections.abc import Mapping

# 与 ``axile/ui/src/lib/derive.ts`` 的 ``REBALANCE_THRESHOLD`` 同步。
REBALANCE_THRESHOLD = 0.5
_ZERO = 1e-6


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


def count_off_symbols(
    positions: list[object],
    target: Mapping[str, float],
    equity: float,
) -> int:
    """
    统计相对目标需要调整的品种数.

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

    symbols = set(cur_mv) | {key for key in target if isinstance(key, str) and key}
    base = equity if equity > 0 else 0.0
    off = 0
    for symbol in symbols:
        cur = ((cur_mv.get(symbol, 0.0) / base) * 100.0) if base > 0 else 0.0
        tgt = float(target.get(symbol, 0.0) or 0.0) * 100.0
        if abs(cur) < _ZERO and abs(tgt) < _ZERO:
            continue
        delta = _round2(cur - tgt)
        if abs(delta) > REBALANCE_THRESHOLD:
            off += 1
    return off


__all__ = ["REBALANCE_THRESHOLD", "count_off_symbols"]

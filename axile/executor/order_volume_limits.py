"""CTP 单笔数量限制：合约上限与用户上限的解析、校验与拆单。

本模块不依赖 openctp SDK，便于离线单测。
"""

from __future__ import annotations

from typing import Any, Iterable

from axile.executor.models.unified_order import OrderType


def _as_positive_int(value: object, *, field: str) -> int | None:
    """把上限/下限字段解析为正整数；缺失或非正返回 None，非法则报错。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field}: 数量限制不能是布尔值")
    if isinstance(value, float) and (not value.is_integer() or value != value):  # noqa: PLR0124
        raise ValueError(f"{field}: 数量限制必须是正整数")
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: 数量限制必须是正整数") from exc
    if number <= 0:
        return None
    return number


def _instrument_field(instrument: object, name: str) -> object:
    if isinstance(instrument, dict):
        return instrument.get(name)
    return getattr(instrument, name, None)


def contract_volume_bounds(instrument: object | None, order_type: OrderType | str) -> tuple[int | None, int | None]:
    """按订单类型读取合约最小/最大单笔数量。

    Returns
    -------
    tuple[int | None, int | None]
        ``(min_volume, max_volume)``；未配置的一侧为 ``None``。
    """
    if instrument is None:
        return None, None
    kind = order_type.value if isinstance(order_type, OrderType) else str(order_type)
    if kind == OrderType.MARKET.value:
        min_name, max_name = "MinMarketOrderVolume", "MaxMarketOrderVolume"
    else:
        min_name, max_name = "MinLimitOrderVolume", "MaxLimitOrderVolume"
    minimum = _as_positive_int(_instrument_field(instrument, min_name), field=min_name)
    maximum = _as_positive_int(_instrument_field(instrument, max_name), field=max_name)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"合约数量限制冲突: {min_name}={minimum} > {max_name}={maximum}")
    return minimum, maximum


def user_max_single_order_size(trade_rule: dict[str, Any] | None) -> int | None:
    """读取用户 ``max_single_order_size``；未设置返回 None。"""
    if not trade_rule:
        return None
    return _as_positive_int(trade_rule.get("max_single_order_size"), field="max_single_order_size")


def effective_max_order_volume(
    instrument: object | None,
    order_type: OrderType | str,
    trade_rule: dict[str, Any] | None = None,
) -> tuple[int | None, int | None]:
    """合并合约与用户限制，返回 ``(min_volume, max_volume)``。

    用户上限与合约上限同时存在时取更严（更小）的最大值；任一侧缺失则忽略该侧。
    """
    minimum, contract_max = contract_volume_bounds(instrument, order_type)
    user_max = user_max_single_order_size(trade_rule)
    caps = [cap for cap in (contract_max, user_max) if cap is not None]
    maximum = min(caps) if caps else None
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"有效数量限制冲突: 最小 {minimum} > 最大 {maximum}")
    return minimum, maximum


def ensure_order_volume_allowed(
    volume: float,
    *,
    instrument: object | None,
    order_type: OrderType | str,
    trade_rule: dict[str, Any] | None = None,
) -> int:
    """在原生发单前校验单笔数量，通过则返回 int(volume)。"""
    if (
        not isinstance(volume, (int, float))
        or isinstance(volume, bool)
        or not float(volume).is_integer()
        or volume <= 0
    ):
        raise ValueError("CTP 下单数量必须为正整数")
    lots = int(volume)
    minimum, maximum = effective_max_order_volume(instrument, order_type, trade_rule)
    if minimum is not None and lots < minimum:
        raise ValueError(f"CTP 下单数量 {lots} 低于合约最小数量 {minimum}")
    if maximum is not None and lots > maximum:
        raise ValueError(f"CTP 下单数量 {lots} 超过单笔上限 {maximum}")
    return lots


def split_order_volumes(total: float, max_size: int | None, *, min_size: int | None = None) -> list[int]:
    """用最少订单覆盖最大合法总量；为尾单预留最小量，绝不向上凑量。

    Parameters
    ----------
    total:
        目标总手数。
    max_size:
        单笔上限；``None`` 表示不拆，整笔返回（仍受 min_size 约束）。
    min_size:
        合约最小量；无法完整覆盖时返回不超过目标的最大合法总量。
    """
    if not isinstance(total, (int, float)) or isinstance(total, bool) or not float(total).is_integer() or total <= 0:
        raise ValueError("拆单数量必须为正整数")
    remaining = int(total)
    floor = 1 if min_size is None else min_size
    if isinstance(floor, bool) or not isinstance(floor, int) or floor <= 0:
        raise ValueError("单笔最小量必须是正整数")
    if max_size is None:
        return [remaining] if remaining >= floor else []
    if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size < floor:
        raise ValueError("单笔上下限冲突或非法")
    count = (remaining + max_size - 1) // max_size
    if remaining < count * floor:
        count = remaining // max_size
        remaining = count * max_size
    slices: list[int] = []
    for index in range(count):
        chunk = min(max_size, remaining - (count - index - 1) * floor)
        slices.append(chunk)
        remaining -= chunk
    return slices


def sum_volumes(volumes: Iterable[int]) -> int:
    """汇总已拆分的整数手数。"""
    return sum(int(v) for v in volumes)


__all__ = [
    "contract_volume_bounds",
    "effective_max_order_volume",
    "ensure_order_volume_allowed",
    "split_order_volumes",
    "sum_volumes",
    "user_max_single_order_size",
]

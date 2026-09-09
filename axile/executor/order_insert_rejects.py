"""CTP 异步报单拒绝：从错误回报解析订单身份并构造拒绝终态字段。

不依赖 openctp SDK，便于离线单测。
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def insert_error_detail(info: object | None) -> tuple[int, str] | None:
    """解析 ErrorID/ErrorMsg；ErrorID==0 或缺失时返回 None（非错误）。"""
    if info is None:
        return None
    try:
        code = int(getattr(info, "ErrorID", 0) or 0)
    except (TypeError, ValueError):
        return None
    if code == 0:
        return None
    message = str(getattr(info, "ErrorMsg", "") or "")
    return code, message


def _row_value(row: object | None, name: str, default: object = "") -> object:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def resolve_insert_reject_order_id(
    *,
    row: object | None,
    order_keys: Mapping[str, Mapping[str, object]],
    trading_day: str,
    front_id: int,
    session_id: int,
    stable_order_id,
) -> str | None:
    """用报单错误帧上的 OrderRef 关联稳定订单 ID。

    显式会话字段优先；缺失时使用当前发单会话。完整稳定键用于精确查询
    ``order_keys``，尚未登记时由跟踪器缓冲早到拒单，绝不跨会话搜索 OrderRef。
    """
    order_ref = str(_row_value(row, "OrderRef", "") or "").strip()
    if not order_ref:
        return None
    day = str(_row_value(row, "TradingDay", trading_day) or trading_day).strip()
    if not day or day != trading_day or len(day) != 8 or not day.isdigit():
        return None
    # CTP SessionID 是有符号 32 位整数；负数和零同样构成稳定会话身份。
    identities = [(_row_value(row, "FrontID", front_id), 1), (_row_value(row, "SessionID", session_id), -(2**31))]
    resolved = []
    for value, minimum in identities:
        if isinstance(value, bool) or re.fullmatch(r"[+-]?[0-9]+", str(value)) is None:
            return None
        number = int(str(value))
        if not minimum <= number <= 2**31 - 1:
            return None
        resolved.append(number)
    # 完整身份既是已登记订单的查询键，也是早到拒单的缓冲键。
    return str(stable_order_id(day, resolved[0], resolved[1], order_ref))


def rejected_order_update(
    *,
    order_id: str,
    symbol: str,
    direction: object,
    order_type: object,
    volume: float,
    price: float,
    channel_type: object,
    offset_flag: object,
    error_id: int,
    error_msg: str,
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造拒绝终态订单的字段字典，供 UnifiedOrder.create 使用。"""
    payload = {
        "order_id": order_id,
        "symbol": symbol,
        "direction": direction,
        "order_type": order_type,
        "volume": volume,
        "price": price,
        "channel_type": channel_type,
        "status": "已拒绝",
        "offset_flag": offset_flag,
        "filled_volume": 0.0,
        "avg_price": 0.0,
        "error_id": error_id,
        "error_msg": error_msg,
        "reject_source": source,
    }
    if extra:
        payload.update(extra)
    return payload


__all__ = [
    "insert_error_detail",
    "rejected_order_update",
    "resolve_insert_reject_order_id",
]

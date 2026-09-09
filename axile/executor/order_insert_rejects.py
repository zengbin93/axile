"""CTP 异步报单拒绝：从错误回报解析订单身份并构造拒绝终态字段。

不依赖 openctp SDK，便于离线单测。
"""

from __future__ import annotations

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

    优先匹配已登记的 ``order_keys``；若尚未登记，则按当前会话拼接稳定键，
    供跟踪器吸收早到拒单。
    """
    order_ref = str(_row_value(row, "OrderRef", "") or "").strip()
    if not order_ref:
        return None
    for order_id, key in order_keys.items():
        if str(key.get("order_ref", "") or "").strip() == order_ref:
            return str(order_id)
    day = str(_row_value(row, "TradingDay", trading_day) or trading_day)
    row_front = _row_value(row, "FrontID", front_id)
    row_session = _row_value(row, "SessionID", session_id)
    try:
        resolved_front = int(row_front or front_id)
        resolved_session = int(row_session or session_id)
    except (TypeError, ValueError):
        resolved_front, resolved_session = front_id, session_id
    return str(stable_order_id(day, resolved_front, resolved_session, order_ref))


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

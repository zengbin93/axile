"""OpenCTP 原生对象到统一模型的纯转换函数。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from openctp_ctp import thosttraderapi as td

from axile.common.trade_channel import TradeChannel
from axile.executor.constants.order_status import OrderStatus
from axile.executor.ctp.combination import split_combination_position
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


def _value(row: object, name: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _float(row: object, name: str) -> float:
    try:
        value = float(_value(row, name, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _time(day: str, clock: str, millisec: int = 0) -> str:
    raw = f"{day} {clock}".strip()
    for pattern in ("%Y%m%d %H:%M:%S", "%Y%m%d"):
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.replace(microsecond=max(0, millisec) * 1000).isoformat()
        except ValueError:
            continue
    return datetime.now().isoformat()


def stable_order_id(trading_day: str, front_id: int, session_id: int, order_ref: str) -> str:
    """构造不随交易所系统编号变化的订单标识。"""
    return f"{trading_day}:{front_id}:{session_id}:{order_ref}"


_ORDER_STATUS = {
    td.THOST_FTDC_OST_AllTraded: OrderStatus.FILLED,
    td.THOST_FTDC_OST_PartTradedQueueing: OrderStatus.PARTIALLY_FILLED,
    td.THOST_FTDC_OST_PartTradedNotQueueing: OrderStatus.CANCELED,
    td.THOST_FTDC_OST_NoTradeQueueing: OrderStatus.PENDING,
    td.THOST_FTDC_OST_NoTradeNotQueueing: OrderStatus.CANCELED,
    td.THOST_FTDC_OST_Canceled: OrderStatus.CANCELED,
    td.THOST_FTDC_OST_Unknown: OrderStatus.SUBMITTED,
    td.THOST_FTDC_OST_NotTouched: OrderStatus.SUBMITTED,
    td.THOST_FTDC_OST_Touched: OrderStatus.SUBMITTED,
}


def order_to_unified(row: object, *, trading_day: str, front_id: int, session_id: int) -> UnifiedOrder:
    """转换原生报单回报或查询帧。"""
    row_front = int(_value(row, "FrontID", front_id) or front_id)
    row_session = int(_value(row, "SessionID", session_id) or session_id)
    order_ref = str(_value(row, "OrderRef", "") or "")
    day = str(_value(row, "TradingDay", trading_day) or trading_day)
    volume = _float(row, "VolumeTotalOriginal")
    traded = _float(row, "VolumeTraded")
    direction = OrderDirection.BUY if _value(row, "Direction") == td.THOST_FTDC_D_Buy else OrderDirection.SELL
    price_type = OrderType.LIMIT if _value(row, "OrderPriceType") == td.THOST_FTDC_OPT_LimitPrice else OrderType.MARKET
    insert_time = str(_value(row, "InsertTime", "") or "")
    return UnifiedOrder.create(
        order_id=stable_order_id(day, row_front, row_session, order_ref),
        symbol=str(_value(row, "InstrumentID", "") or ""),
        direction=direction.value,
        order_type=price_type.value,
        volume=volume,
        price=_float(row, "LimitPrice"),
        channel_type=TradeChannel.CTP,
        status=_ORDER_STATUS.get(_value(row, "OrderStatus"), OrderStatus.REJECTED),
        filled_volume=traded,
        avg_price=_float(row, "LimitPrice") if traded else 0.0,
        create_time=_time(day, insert_time) if insert_time else datetime.now().isoformat(),
        order_ref=order_ref,
        front_id=row_front,
        session_id=row_session,
        exchange_id=str(_value(row, "ExchangeID", "") or ""),
        order_sys_id=str(_value(row, "OrderSysID", "") or "").strip(),
        offset_flag=str(_value(row, "CombOffsetFlag", "") or "")[:1],
        status_msg=str(_value(row, "StatusMsg", "") or ""),
    )


def trade_to_unified(row: object, *, trading_day: str, front_id: int, session_id: int) -> TradeRecord:
    """转换原生成交帧并保持稳定订单关联。"""
    day = str(_value(row, "TradingDay", trading_day) or trading_day)
    order_ref = str(_value(row, "OrderRef", "") or "")
    row_front = int(_value(row, "FrontID", front_id) or front_id)
    row_session = int(_value(row, "SessionID", session_id) or session_id)
    price = _float(row, "Price")
    volume = _float(row, "Volume")
    return TradeRecord.create(
        trade_id=str(_value(row, "TradeID", "") or ""),
        symbol=str(_value(row, "InstrumentID", "") or ""),
        order_id=stable_order_id(day, row_front, row_session, order_ref),
        trade_time=_time(day, str(_value(row, "TradeTime", "") or "")),
        trade_volume=volume,
        trade_price=price,
        order_ref=order_ref,
        exchange_id=str(_value(row, "ExchangeID", "") or ""),
        order_sys_id=str(_value(row, "OrderSysID", "") or "").strip(),
        direction=str(_value(row, "Direction", "") or ""),
        offset_flag=str(_value(row, "OffsetFlag", "") or ""),
    )


def quote_to_unified(row: object) -> UnifiedPriceData:
    """转换原生深度行情帧。"""
    day = str(_value(row, "ActionDay", "") or _value(row, "TradingDay", "") or "")
    clock = str(_value(row, "UpdateTime", "") or "")
    millisec = int(_value(row, "UpdateMillisec", 0) or 0)
    update_time = _time(day, clock, millisec)
    timestamp = int(datetime.fromisoformat(update_time).timestamp() * 1000)
    bid = _float(row, "BidPrice1")
    ask = _float(row, "AskPrice1")
    return UnifiedPriceData(
        symbol=str(_value(row, "InstrumentID", "") or ""),
        last_price=_float(row, "LastPrice"),
        bid_price=bid,
        ask_price=ask,
        bid_volume=_float(row, "BidVolume1"),
        ask_volume=_float(row, "AskVolume1"),
        volume=_float(row, "Volume"),
        turnover=_float(row, "Turnover"),
        timestamp=timestamp,
        update_time=update_time,
        book_valid=bid > 0 and ask > 0,
        **{f"bid_price_{level}": _float(row, f"BidPrice{level}") for level in range(2, 6)},
        **{f"ask_price_{level}": _float(row, f"AskPrice{level}") for level in range(2, 6)},
        **{f"bid_volume_{level}": _float(row, f"BidVolume{level}") for level in range(2, 6)},
        **{f"ask_volume_{level}": _float(row, f"AskVolume{level}") for level in range(2, 6)},
        extra={"exchange_id": str(_value(row, "ExchangeID", "") or "")},
    )


def account_to_unified(
    account: object, position_rows: list[object], instruments: dict[str, object]
) -> UnifiedAccountAssets:
    """聚合资金与原生持仓帧为统一账户快照。"""
    expanded: list[object] = []
    for row in position_rows:
        split = split_combination_position(row)
        expanded.extend(split if split is not None else [row])
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in expanded:
        symbol = str(_value(row, "InstrumentID", "") or "")
        native_direction = str(_value(row, "PosiDirection", "") or "")
        direction = PositionDirection.LONG if native_direction == td.THOST_FTDC_PD_Long else PositionDirection.SHORT
        key = (symbol, direction.value)
        group = groups.setdefault(
            key, {"volume": 0.0, "today": 0.0, "yesterday": 0.0, "frozen": 0.0, "cost": 0.0, "origin": None}
        )
        volume = _float(row, "Position")
        today = _float(row, "TodayPosition")
        yesterday = _float(row, "YdPosition")
        if not today and not yesterday:
            (
                group.__setitem__("today", group["today"] + volume)
                if _value(row, "PositionDate") == td.THOST_FTDC_PSD_Today
                else group.__setitem__("yesterday", group["yesterday"] + volume)
            )
        else:
            group["today"] += today
            group["yesterday"] += yesterday
        group["volume"] += volume
        group["frozen"] += (
            _float(row, "LongFrozen") if direction is PositionDirection.LONG else _float(row, "ShortFrozen")
        )
        group["cost"] += _float(row, "PositionCost")
        group["origin"] = _value(row, "combination_origin", group["origin"])
    positions: list[Position] = []
    for (symbol, direction), group in groups.items():
        instrument = instruments.get(symbol)
        multiplier = _float(instrument, "VolumeMultiple") or 1.0
        volume = group["volume"]
        avg_price = group["cost"] / (volume * multiplier) if volume else None
        extra = {
            "long_td" if direction == PositionDirection.LONG.value else "short_td": group["today"],
            "long_yd" if direction == PositionDirection.LONG.value else "short_yd": group["yesterday"],
            "frozen": group["frozen"],
        }
        if group["origin"]:
            extra["combination_origin"] = group["origin"]
        positions.append(
            Position(
                symbol=symbol,
                volume=volume,
                available_volume=max(0.0, volume - group["frozen"]),
                market_value=group["cost"],
                direction=direction,
                avg_price=avg_price,
                extra=extra,
            )
        )
    return UnifiedAccountAssets(
        available_cash=_float(account, "Available"),
        total_asset=_float(account, "Balance"),
        market_value=sum(position.market_value for position in positions),
        positions=positions,
        extra={
            "account_id": str(_value(account, "AccountID", "") or ""),
            "trading_day": str(_value(account, "TradingDay", "") or ""),
        },
    )


__all__ = ["account_to_unified", "order_to_unified", "quote_to_unified", "stable_order_id", "trade_to_unified"]

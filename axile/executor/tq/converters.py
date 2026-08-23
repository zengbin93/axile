"""TqSdk 快照到 Axile 统一模型的纯转换函数."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from axile.common.trade_channel import TradeChannel
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData
from axile.executor.tq.symbols import TQSymbolResolver


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


def _iso_from_nano(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000_000).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now().isoformat()


def _quote_time(value: object) -> tuple[str, int]:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.isoformat(), int(parsed.timestamp() * 1000)
        except ValueError:
            pass
    update_time = _iso_from_nano(value)
    try:
        timestamp = int(int(value) / 1_000_000)
    except (TypeError, ValueError):
        timestamp = int(datetime.fromisoformat(update_time).timestamp() * 1000)
    return update_time, timestamp


def quote_to_unified(row: object, resolver: TQSymbolResolver) -> UnifiedPriceData:
    """转换天勤行情快照."""
    local = str(_value(row, "instrument_id", "") or _value(row, "symbol", ""))
    exchange = str(_value(row, "exchange_id", "") or "")
    full_symbol = f"{exchange}.{local}" if exchange and "." not in local else local
    timestamp_nano = _value(row, "datetime", 0)
    update_time, timestamp = _quote_time(timestamp_nano)
    bid = _float(row, "bid_price1")
    ask = _float(row, "ask_price1")
    last = _float(row, "last_price")
    return UnifiedPriceData(
        symbol=resolver.to_axile(full_symbol),
        last_price=last,
        bid_price=bid,
        ask_price=ask,
        bid_volume=_float(row, "bid_volume1"),
        ask_volume=_float(row, "ask_volume1"),
        volume=_float(row, "volume"),
        turnover=_float(row, "amount"),
        timestamp=timestamp,
        update_time=update_time,
        book_valid=bid > 0 and ask > 0,
        **{f"bid_price_{level}": _float(row, f"bid_price{level}") for level in range(2, 6)},
        **{f"ask_price_{level}": _float(row, f"ask_price{level}") for level in range(2, 6)},
        **{f"bid_volume_{level}": _float(row, f"bid_volume{level}") for level in range(2, 6)},
        **{f"ask_volume_{level}": _float(row, f"ask_volume{level}") for level in range(2, 6)},
        extra={
            "tq_symbol": full_symbol,
            "exchange_id": str(_value(row, "exchange_id", "") or ""),
            "price_tick": _float(row, "price_tick"),
            "volume_multiple": _float(row, "volume_multiple"),
        },
    )


def _order_status(row: object) -> str:
    status = str(_value(row, "status", "") or "")
    volume = _float(row, "volume_orign")
    left = _float(row, "volume_left")
    filled = max(0.0, volume - left)
    if status == "ALIVE":
        return OrderStatus.PARTIALLY_FILLED if filled else OrderStatus.PENDING
    if left <= 0 and volume > 0:
        return OrderStatus.FILLED
    message = str(_value(row, "last_msg", "") or "")
    if any(word in message for word in ("拒绝", "失败", "错误", "不合法")):
        return OrderStatus.REJECTED
    return OrderStatus.CANCELED


def order_to_unified(row: object, resolver: TQSymbolResolver) -> UnifiedOrder:
    """转换天勤订单快照."""
    exchange = str(_value(row, "exchange_id", "") or "")
    local = str(_value(row, "instrument_id", "") or "")
    full_symbol = f"{exchange}.{local}" if exchange and "." not in local else local
    volume = _float(row, "volume_orign")
    left = _float(row, "volume_left")
    return UnifiedOrder.create(
        order_id=str(_value(row, "order_id", "") or ""),
        symbol=resolver.to_axile(full_symbol),
        direction=OrderDirection.BUY.value if _value(row, "direction") == "BUY" else OrderDirection.SELL.value,
        order_type=OrderType.MARKET.value if _value(row, "price_type") == "ANY" else OrderType.LIMIT.value,
        volume=volume,
        price=_float(row, "limit_price"),
        channel_type=TradeChannel.TQ,
        status=_order_status(row),
        filled_volume=max(0.0, volume - left),
        avg_price=_float(row, "trade_price"),
        insert_date_time=_value(row, "insert_date_time", 0),
        exchange_id=exchange,
        offset=str(_value(row, "offset", "") or ""),
        last_msg=str(_value(row, "last_msg", "") or ""),
        tq_symbol=full_symbol,
    )


def trade_to_unified(row: object, resolver: TQSymbolResolver) -> TradeRecord:
    """转换天勤成交快照."""
    exchange = str(_value(row, "exchange_id", "") or "")
    local = str(_value(row, "instrument_id", "") or "")
    full_symbol = f"{exchange}.{local}" if exchange and "." not in local else local
    return TradeRecord.create(
        trade_id=str(_value(row, "trade_id", "") or _value(row, "exchange_trade_id", "")),
        symbol=resolver.to_axile(full_symbol),
        order_id=str(_value(row, "order_id", "") or ""),
        trade_time=_iso_from_nano(_value(row, "trade_date_time", 0)),
        trade_volume=_float(row, "trade_volume"),
        trade_price=_float(row, "trade_price"),
        exchange_id=exchange,
        direction=str(_value(row, "direction", "") or ""),
        offset=str(_value(row, "offset", "") or ""),
        tq_symbol=full_symbol,
    )


def account_to_unified(
    account: object,
    position_rows: dict[str, object],
    resolver: TQSymbolResolver,
) -> UnifiedAccountAssets:
    """聚合天勤资金与持仓快照."""
    positions: list[Position] = []
    for full_symbol, row in position_rows.items():
        symbol = resolver.to_axile(str(full_symbol))
        long_td = _float(row, "pos_long_today")
        long_yd = _float(row, "pos_long_his")
        short_td = _float(row, "pos_short_today")
        short_yd = _float(row, "pos_short_his")
        long_total = long_td + long_yd
        short_total = short_td + short_yd
        common_extra = {
            "long_td": long_td,
            "long_yd": long_yd,
            "short_td": short_td,
            "short_yd": short_yd,
            "long_total": long_total,
            "short_total": short_total,
            "net_position": long_total - short_total,
            "tq_symbol": full_symbol,
        }
        if long_total:
            frozen = _float(row, "volume_long_frozen")
            positions.append(
                Position(
                    symbol=symbol,
                    volume=long_total,
                    available_volume=max(0.0, long_total - frozen),
                    market_value=_float(row, "position_cost_long"),
                    direction=PositionDirection.LONG,
                    avg_price=_float(row, "open_price_long") or None,
                    extra={**common_extra, "frozen": frozen},
                )
            )
        if short_total:
            frozen = _float(row, "volume_short_frozen")
            positions.append(
                Position(
                    symbol=symbol,
                    volume=short_total,
                    available_volume=max(0.0, short_total - frozen),
                    market_value=_float(row, "position_cost_short"),
                    direction=PositionDirection.SHORT,
                    avg_price=_float(row, "open_price_short") or None,
                    extra={**common_extra, "frozen": frozen},
                )
            )
    return UnifiedAccountAssets(
        available_cash=_float(account, "available"),
        total_asset=_float(account, "balance"),
        market_value=sum(position.market_value for position in positions),
        positions=positions,
        extra={"account_id": str(_value(account, "account_id", "") or "")},
    )


__all__ = ["account_to_unified", "order_to_unified", "quote_to_unified", "trade_to_unified"]

from __future__ import annotations

import math

from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_account_assets import PositionDirection
from axile.executor.tq.converters import account_to_unified, order_to_unified, quote_to_unified, trade_to_unified
from axile.executor.tq.symbols import TQInstrument, TQSymbolResolver


def _resolver() -> TQSymbolResolver:
    return TQSymbolResolver([TQInstrument("SHFE.rb2610", "rb2610", "SHFE", "FUTURE")])


def test_quote_and_order_return_to_common_symbol() -> None:
    resolver = _resolver()
    quote = quote_to_unified(
        {
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "last_price": 3200,
            "bid_price1": 3199,
            "ask_price1": 3201,
            "bid_volume1": 2,
            "ask_volume1": 3,
            "datetime": 1_700_000_000_000_000_000,
        },
        resolver,
    )
    order = order_to_unified(
        {
            "order_id": "o1",
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "direction": "BUY",
            "offset": "OPEN",
            "price_type": "LIMIT",
            "volume_orign": 2,
            "volume_left": 0,
            "limit_price": 3200,
            "status": "FINISHED",
        },
        resolver,
    )

    assert quote.symbol == "rb2610"
    assert order.symbol == "rb2610"
    assert order.status == OrderStatus.FILLED


def test_trade_reads_tqsdk_trade_entity_fields() -> None:
    trade = trade_to_unified(
        {
            "trade_id": "t1",
            "order_id": "o1",
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "direction": "SELL",
            "offset": "CLOSE",
            "price": 3092.0,
            "volume": 4,
            "trade_date_time": 1_700_000_000_000_000_000,
        },
        _resolver(),
    )

    assert trade.symbol == "rb2610"
    assert trade.order_id == "o1"
    assert trade.trade_volume == 4.0
    assert trade.trade_price == 3092.0
    assert trade.trade_value == 4.0 * 3092.0
    assert trade.extra["offset"] == "CLOSE"


def test_trade_price_nan_falls_back_to_zero() -> None:
    trade = trade_to_unified(
        {
            "trade_id": "t2",
            "order_id": "o1",
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "direction": "BUY",
            "offset": "OPEN",
            "price": float("nan"),
            "volume": 1,
            "trade_date_time": 1_700_000_000_000_000_000,
        },
        _resolver(),
    )

    assert math.isfinite(trade.trade_price)
    assert trade.trade_price == 0.0
    assert trade.trade_value == 0.0


def test_positions_expose_complete_today_yesterday_breakdown() -> None:
    assets = account_to_unified(
        {"available": 900_000, "balance": 1_000_000},
        {
            "SHFE.rb2610": {
                "pos_long_today": 2,
                "pos_long_his": 3,
                "pos_short_today": 1,
                "pos_short_his": 0,
                "position_cost_long": 50_000,
                "position_cost_short": 10_000,
            }
        },
        _resolver(),
    )

    assert [(position.direction, position.volume) for position in assets.positions] == [
        (PositionDirection.LONG.value, 5),
        (PositionDirection.SHORT.value, 1),
    ]
    assert assets.positions[0].extra["net_position"] == 4
    assert assets.positions[1].extra["long_yd"] == 3

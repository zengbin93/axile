"""CTP 自然时间、时区及未知时间回归测试。"""

import os
import time
from datetime import datetime, timezone

import pytest

from axile.executor.algorithms.utils.order_tracker import OrderTracker
from axile.executor.ctp.converters import order_to_unified, quote_to_unified, trade_to_unified


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="requires POSIX tzset")
def test_quote_timestamp_is_independent_of_host_timezone():
    row = dict(ActionDay="20260904", TradingDay="20260907", UpdateTime="21:05:00", UpdateMillisec=123)
    previous = os.environ.get("TZ")
    try:
        quotes = []
        for host_tz in ("UTC", "Asia/Shanghai"):
            os.environ["TZ"] = host_tz
            time.tzset()
            quotes.append(quote_to_unified(row))
        expected = int(datetime(2026, 9, 4, 13, 5, 0, 123000, tzinfo=timezone.utc).timestamp() * 1000)
        assert [q.timestamp for q in quotes] == [expected, expected]
        assert all(q.update_time == "2026-09-04T21:05:00.123000+08:00" for q in quotes)
        assert all(q.extra["trading_day"] == "20260907" for q in quotes)
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize(
    "day,clock,expected",
    [
        ("20260904", "21:05:00", "2026-09-04T21:05:00+08:00"),
        ("20260905", "00:05:00", "2026-09-05T00:05:00+08:00"),
        ("20260907", "09:05:00", "2026-09-07T09:05:00+08:00"),
    ],
)
def test_trade_natural_date_is_separate_from_trading_day(day, clock, expected):
    trade = trade_to_unified(
        dict(TradeDate=day, TradeTime=clock, TradingDay="20260907", OrderRef="1", Volume=2, Price=100),
        trading_day="20260907",
        front_id=1,
        session_id=2,
    )
    assert trade.trade_time == expected
    assert trade.order_id == "20260907:1:2:1"
    assert trade.extra["trading_day"] == "20260907"
    assert trade.extra["event_time_source"] == "TradeDate"
    assert trade.extra["event_time_status"] == "native"
    assert trade.trade_volume == 2


@pytest.mark.parametrize(
    "day,clock", [("", "21:05:00"), ("20260230", "21:05:00"), ("20260904", ""), ("20260904", "25:00:00")]
)
def test_unknown_trade_time_preserves_trade_without_fabricating_time(day, clock):
    trade = trade_to_unified(
        dict(TradeDate=day, TradeTime=clock, TradingDay="20260907", Volume=2),
        trading_day="20260907",
        front_id=1,
        session_id=2,
    )
    assert trade.trade_time == ""
    assert trade.trade_volume == 2
    assert trade.extra["event_time_status"] == "unknown"
    assert trade.extra["event_date"] == day


@pytest.mark.parametrize(
    "changes",
    [
        dict(ActionDay=""),
        dict(ActionDay="20260230"),
        dict(UpdateTime=""),
        dict(UpdateMillisec=1000),
        dict(UpdateMillisec=-1),
        dict(UpdateMillisec="bad"),
    ],
)
def test_unknown_quote_time_is_not_fresh(changes):
    row = dict(
        ActionDay="20260904",
        TradingDay="20260907",
        UpdateTime="21:05:00",
        UpdateMillisec=123,
        LastPrice=100,
        BidPrice1=99,
        AskPrice1=101,
    )
    row.update(changes)
    quote = quote_to_unified(row)
    assert quote.timestamp == 0
    assert quote.update_time == ""
    assert quote.extra["event_time_status"] == "unknown"
    assert not quote.is_valid()
    # 调用实际新鲜度门禁，未知时间不能成为可用的新行情。
    assert not OrderTracker._price_is_fresh(None, quote, time.time())


def test_order_uses_insert_date_and_keeps_trading_day_identity():
    order = order_to_unified(
        dict(InsertDate="20260904", InsertTime="21:05:00", TradingDay="20260907"),
        trading_day="20260907",
        front_id=1,
        session_id=2,
    )
    assert order.create_time == "2026-09-04T21:05:00+08:00"
    assert order.extra["trading_day"] == "20260907"
    assert order.update_time.endswith("+08:00")

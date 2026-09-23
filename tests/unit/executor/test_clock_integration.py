"""交易日期、事件时间戳与等待使用可替换时钟。"""

import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from axile.channels.cn_futures import canonicalize_cn_futures_symbol
from axile.executor.algorithms.utils import clock as clock_module
from axile.executor.ctp.options import OptionActionRecord, OptionActionType, fail_option_action
from axile.executor.market_session import is_china_futures_trading_day
from axile.executor.tq.converters import _iso_from_nano
from axile.executor.tq.symbols import TQSymbolResolver


class FixedClock:
    """只提供本测试需要的时钟操作。"""

    def __init__(self, timestamp: float) -> None:
        self.timestamp = timestamp

    def time(self) -> float:
        return self.timestamp

    def sleep(self, seconds: float) -> None:
        self.timestamp += seconds


def test_calendar_and_event_fallbacks_follow_simulated_clock(monkeypatch) -> None:
    saturday = datetime(2037, 1, 3, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(clock_module, "_default_clock", FixedClock(saturday.timestamp()))

    assert not is_china_futures_trading_day()
    assert canonicalize_cn_futures_symbol("TA3701") == "TA701"
    assert TQSymbolResolver([])._reference_year == 2037
    assert _iso_from_nano(None) == clock_module.clock_now_iso()

    record = OptionActionRecord("1", "TA701C5000", OptionActionType.EXERCISE, 1)
    failed = fail_option_action(record, object(), "test")
    assert failed.finish_time == clock_module.clock_now_iso()


def test_virtual_deadlines_and_waits_advance_without_wall_clock(monkeypatch) -> None:
    clock = FixedClock(1000)
    monkeypatch.setattr(clock_module, "_default_clock", clock)

    deadline = clock_module.clock_monotonic() + 5
    condition = threading.Condition()
    with condition:
        clock_module.clock_condition_wait(condition, 3)
    asyncio.run(clock_module.clock_async_sleep(2))

    assert clock_module.clock_monotonic() == deadline

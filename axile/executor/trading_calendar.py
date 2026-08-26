"""执行器使用的轻量交易日历接口与 Shinny 实现。"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Protocol

from shinny_calendar import CalendarUtility

CHINA_CALENDAR_ID = "china"
SHINNY_COVERAGE_START = date(2003, 1, 1)
SHINNY_COVERAGE_END = date(2026, 12, 31)


class TradingCalendar(Protocol):
    """定义渠道执行器所需的最小交易日历能力。"""

    def is_open(self, calendar_id: str, day: date) -> bool | None:
        """返回指定自然日的开闭市状态，无法判断时返回 ``None``。"""


class ShinnyTradingCalendar:
    """直接读取 Shinny 内置中国节假日数据的只读日历。"""

    def __init__(self) -> None:
        self._calendar = CalendarUtility()

    def is_open(self, calendar_id: str, day: date) -> bool | None:
        """判断 ``china`` 日历中的自然日是否为交易日。"""
        if calendar_id != CHINA_CALENDAR_ID or not SHINNY_COVERAGE_START <= day <= SHINNY_COVERAGE_END:
            return None
        moment = datetime.combine(day, time.min)
        return self._calendar.trading_day(moment) == day


__all__ = [
    "CHINA_CALENDAR_ID",
    "SHINNY_COVERAGE_END",
    "SHINNY_COVERAGE_START",
    "ShinnyTradingCalendar",
    "TradingCalendar",
]

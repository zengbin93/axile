"""轻量 Shinny 交易日历测试。"""

from datetime import date

from axile.executor.trading_calendar import ShinnyTradingCalendar


def test_shinny_calendar_covers_workday_weekend_and_holiday() -> None:
    calendar = ShinnyTradingCalendar()

    assert calendar.is_open("china", date(2026, 1, 5)) is True
    assert calendar.is_open("china", date(2026, 1, 10)) is False
    assert calendar.is_open("china", date(2026, 10, 1)) is False


def test_shinny_calendar_returns_none_outside_contract() -> None:
    calendar = ShinnyTradingCalendar()

    assert calendar.is_open("china", date(2026, 12, 31)) is True
    assert calendar.is_open("vendor", date(2026, 1, 5)) is None
    assert calendar.is_open("china", date(2002, 12, 31)) is None
    assert calendar.is_open("china", date(2027, 1, 1)) is None

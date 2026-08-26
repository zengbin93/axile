"""渠道轻量交易日历决策测试。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from axile.common.trade_channel import TradeChannel
from axile.server.trading_calendar import (
    CalendarDecisionStatus,
    CalendarUnavailableReason,
    evaluate_channel_calendar_day,
    evaluate_channel_calendar_moment,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Calendar:
    def __init__(self, days: dict[date, bool | None]) -> None:
        self.days = days

    def is_open(self, calendar_id: str, day: date) -> bool | None:
        assert calendar_id == "china"
        return self.days.get(day)


class _BrokenCalendar:
    def is_open(self, _calendar_id: str, _day: date) -> bool | None:
        raise RuntimeError("calendar failed")


@pytest.mark.parametrize("channel", [TradeChannel.CTP, TradeChannel.GM, TradeChannel.TQ])
def test_domestic_channels_share_china_calendar(channel: TradeChannel) -> None:
    decision = evaluate_channel_calendar_day(
        channel,
        date(2026, 8, 29),
        calendar=_Calendar({date(2026, 8, 29): False}),
    )

    assert decision.calendar_id == "china"
    assert decision.status is CalendarDecisionStatus.AVAILABLE_CLOSED


def test_calendar_uncovered_and_read_failure_are_distinct() -> None:
    uncovered = evaluate_channel_calendar_day(TradeChannel.CTP, date(2027, 1, 1), calendar=_Calendar({}))
    failed = evaluate_channel_calendar_day(TradeChannel.CTP, date(2026, 8, 27), calendar=_BrokenCalendar())

    assert uncovered.status is CalendarDecisionStatus.UNAVAILABLE
    assert uncovered.unavailable_reason is CalendarUnavailableReason.UNCOVERED
    assert failed.status is CalendarDecisionStatus.UNAVAILABLE
    assert failed.unavailable_reason is CalendarUnavailableReason.READ_FAILED


def test_friday_night_maps_to_monday_trading_day() -> None:
    calendar = _Calendar(
        {
            date(2026, 8, 21): True,
            date(2026, 8, 22): False,
            date(2026, 8, 23): False,
            date(2026, 8, 24): True,
        }
    )

    decision = evaluate_channel_calendar_moment(
        TradeChannel.CTP,
        datetime(2026, 8, 21, 21, 30, tzinfo=_SHANGHAI),
        calendar=calendar,
    )

    assert decision.status is CalendarDecisionStatus.AVAILABLE_OPEN
    assert decision.day == date(2026, 8, 24)


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 8, 24, 21, 30, tzinfo=_SHANGHAI),
        datetime(2026, 8, 25, 1, 30, tzinfo=_SHANGHAI),
    ],
)
def test_adjacent_night_and_early_morning_map_to_next_trading_day(moment: datetime) -> None:
    calendar = _Calendar({date(2026, 8, 24): True, date(2026, 8, 25): True})

    decision = evaluate_channel_calendar_moment(TradeChannel.CTP, moment, calendar=calendar)

    assert decision.status is CalendarDecisionStatus.AVAILABLE_OPEN
    assert decision.day == date(2026, 8, 25)


def test_holiday_eve_has_no_corresponding_night_session() -> None:
    days = {date(2026, 9, 30): True, date(2026, 10, 8): True}
    days.update({date(2026, 10, day): False for day in range(1, 8)})

    decision = evaluate_channel_calendar_moment(
        TradeChannel.CTP,
        datetime(2026, 9, 30, 21, 30, tzinfo=_SHANGHAI),
        calendar=_Calendar(days),
    )

    assert decision.status is CalendarDecisionStatus.AVAILABLE_CLOSED
    assert decision.reason_code == "CALENDAR.NO_NIGHT_SESSION"

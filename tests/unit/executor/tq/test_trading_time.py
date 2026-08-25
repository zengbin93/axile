from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from axile.executor.tq.trading_time import check_tq_trading_time

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Calendar:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._rows


class _Api:
    def __init__(
        self,
        *,
        day: list[object],
        night: list[object],
        calendar_rows: list[dict[str, object]],
    ) -> None:
        self.quote = SimpleNamespace(trading_time=SimpleNamespace(day=day, night=night))
        self.calendar_rows = calendar_rows
        self.calendar_calls: list[tuple[date, date]] = []

    def get_quote(self, symbol: str) -> object:
        assert symbol == "SHFE.rb2610"
        return self.quote

    def get_trading_calendar(self, start_dt: date, end_dt: date) -> _Calendar:
        self.calendar_calls.append((start_dt, end_dt))
        return _Calendar(self.calendar_rows)


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=_SHANGHAI)


@pytest.mark.parametrize(
    ("night", "moment", "available"),
    [
        (["20:55:00", "23:00:00"], "2026-08-25T20:55:00", True),
        (["21:00:00", "23:00:00"], "2026-08-25T22:59:59", True),
        (["21:00:00", "23:00:00"], "2026-08-25T23:00:00", False),
        (["21:00:00", "25:00:00"], "2026-08-26T00:59:59", True),
        (["21:00:00", "25:00:00"], "2026-08-26T01:00:00", False),
        (["21:00:00", "26:30:00"], "2026-08-26T02:29:59", True),
        (["21:00:00", "26:30:00"], "2026-08-26T02:30:00", False),
    ],
)
def test_checks_night_session_boundaries_per_contract(
    night: list[str], moment: str, available: bool
) -> None:
    api = _Api(
        day=[],
        night=[night],
        calendar_rows=[
            {"date": date(2026, 8, 25), "trading": True},
            {"date": date(2026, 8, 26), "trading": True},
        ],
    )

    decision = check_tq_trading_time(api, "SHFE.rb2610", now=_at(moment))

    assert decision.available is available


def test_fails_closed_when_any_trading_time_range_is_invalid() -> None:
    api = _Api(
        day=[["09:00:00", "10:15:00"], ["13:30:00", "invalid"]],
        night=[],
        calendar_rows=[{"date": date(2026, 8, 25), "trading": True}],
    )

    decision = check_tq_trading_time(api, "SHFE.rb2610", now=_at("2026-08-25T09:30:00"))

    assert decision.available is False
    assert decision.reason == "TqSdk 合约交易时段不可用"


def test_rejects_daytime_lunch_break_and_non_trading_day() -> None:
    api = _Api(
        day=[["09:00:00", "10:15:00"], ["10:30:00", "11:30:00"], ["13:30:00", "15:00:00"]],
        night=[],
        calendar_rows=[{"date": date(2026, 8, 25), "trading": False}],
    )

    lunch = check_tq_trading_time(api, "SHFE.rb2610", now=_at("2026-08-25T10:20:00"))
    closed_day = check_tq_trading_time(api, "SHFE.rb2610", now=_at("2026-08-25T09:30:00"))

    assert lunch.available is False
    assert lunch.reason == "当前不在该合约的 TqSdk 交易时段"
    assert closed_day.available is False
    assert closed_day.reason == "当前不是 TqSdk 交易日"


def test_rejects_night_before_holiday_and_friday_night() -> None:
    before_holiday = _Api(
        day=[],
        night=[["21:00:00", "26:30:00"]],
        calendar_rows=[
            {"date": date(2026, 9, 30), "trading": True},
            {"date": date(2026, 10, 1), "trading": False},
            {"date": date(2026, 10, 9), "trading": True},
        ],
    )
    friday = _Api(
        day=[],
        night=[["21:00:00", "26:30:00"]],
        calendar_rows=[
            {"date": date(2026, 8, 28), "trading": True},
            {"date": date(2026, 8, 29), "trading": False},
            {"date": date(2026, 8, 30), "trading": False},
            {"date": date(2026, 8, 31), "trading": True},
        ],
    )

    holiday_decision = check_tq_trading_time(before_holiday, "SHFE.rb2610", now=_at("2026-09-30T21:00:00"))
    friday_decision = check_tq_trading_time(friday, "SHFE.rb2610", now=_at("2026-08-29T01:00:00"))

    assert holiday_decision.available is False
    assert holiday_decision.reason == "当前夜盘对应交易日无效"
    assert friday_decision.available is False
    assert friday_decision.reason == "当前夜盘对应交易日无效"


def test_fails_closed_with_distinct_reasons_for_metadata_and_calendar() -> None:
    metadata_api = _Api(day=[], night=[], calendar_rows=[])
    metadata_api.quote = SimpleNamespace(trading_time=SimpleNamespace(day=None, night=[]))
    calendar_api = _Api(
        day=[["09:00:00", "10:15:00"]],
        night=[],
        calendar_rows=[],
    )

    metadata_decision = check_tq_trading_time(metadata_api, "SHFE.rb2610", now=_at("2026-08-25T09:30:00"))
    calendar_decision = check_tq_trading_time(calendar_api, "SHFE.rb2610", now=_at("2026-08-25T09:30:00"))

    assert metadata_decision.available is False
    assert metadata_decision.reason == "TqSdk 合约交易时段不可用"
    assert calendar_decision.available is False
    assert calendar_decision.reason == "TqSdk 交易日历不可用"

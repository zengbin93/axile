"""CTP 品种级交易时段判定测试。"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from axile.executor.ctp_product_sessions import (
    CTP_PRODUCT_SESSIONS,
    CtpProductSession,
    decide_ctp_product_session,
    get_ctp_product_sessions,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _session(begin: str, end: str) -> CtpProductSession:
    return CtpProductSession(
        exchange_id="SHFE",
        product_id="ag",
        segment_no=1,
        time_begin=time.fromisoformat(begin),
        time_end=time.fromisoformat(end),
    )


def _open_days(*days: date) -> dict[date, bool]:
    return {day: True for day in days}


def _calendar(days: dict[date, bool]):
    return lambda day: days.get(day)


@pytest.mark.parametrize(
    ("now", "sessions", "expected"),
    [
        ("2026-08-24T21:29:00", [_session("21:00", "23:00")], True),
        ("2026-08-24T23:00:00", [_session("21:00", "23:00")], False),
        ("2026-08-24T23:30:00", [_session("21:00", "01:00")], True),
        ("2026-08-25T01:00:00", [_session("21:00", "01:00")], False),
        ("2026-08-25T01:30:00", [_session("21:00", "02:30")], True),
        ("2026-08-25T02:30:00", [_session("21:00", "02:30")], False),
        ("2026-08-25T10:15:00", [_session("09:00", "10:15")], False),
        ("2026-08-25T11:30:00", [_session("10:30", "11:30")], False),
        (
            "2026-08-25T12:00:00",
            [_session("09:00", "10:15"), _session("10:30", "11:30"), _session("13:30", "15:00")],
            False,
        ),
        ("2026-08-25T15:00:00", [_session("13:30", "15:00")], False),
    ],
)
def test_product_session_uses_left_closed_right_open_intervals(
    now: str, sessions: list[CtpProductSession], expected: bool
) -> None:
    moment = datetime.fromisoformat(now).replace(tzinfo=_SHANGHAI)
    calendar = _calendar(_open_days(date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 25)))

    decision = decide_ctp_product_session(sessions, now=moment, calendar_is_open=calendar)

    assert decision.allowed is expected
    assert decision.reason_code == (None if expected else "CTP.SESSION.CLOSED")


@pytest.mark.parametrize(
    ("product_id", "sessions", "expected"),
    [
        ("CF", [_session("21:00", "23:00")], True),
        ("cu", [_session("21:00", "01:00")], True),
        ("ag", [_session("21:00", "02:30")], True),
        ("IF", [_session("09:30", "11:30")], False),
        ("IM", [_session("09:30", "11:30")], False),
    ],
)
def test_products_are_decided_independently_at_2129(
    product_id: str, sessions: list[CtpProductSession], expected: bool
) -> None:
    now = datetime(2026, 8, 24, 21, 29, tzinfo=_SHANGHAI)
    calendar = _calendar(_open_days(date(2026, 8, 24), date(2026, 8, 25)))

    decision = decide_ctp_product_session(sessions, now=now, calendar_is_open=calendar)

    assert decision.allowed is expected
    assert decision.reason_code == (None if expected else "CTP.SESSION.CLOSED")
    assert product_id


@pytest.mark.parametrize(
    "moment", [datetime(2026, 8, 22, 0, 30, tzinfo=_SHANGHAI), datetime(2026, 8, 22, 1, 30, tzinfo=_SHANGHAI)]
)
def test_friday_night_continues_into_saturday_as_monday_trading_day(moment: datetime) -> None:
    calendar = _calendar(
        {date(2026, 8, 21): True, date(2026, 8, 22): False, date(2026, 8, 23): False, date(2026, 8, 24): True}
    )

    decision = decide_ctp_product_session([_session("21:00", "02:30")], now=moment, calendar_is_open=calendar)

    assert decision.allowed is True


def test_night_session_is_closed_before_holiday_transition() -> None:
    now = datetime(2026, 10, 1, 0, 30, tzinfo=_SHANGHAI)
    calendar = _calendar(
        {
            date(2026, 9, 30): True,
            date(2026, 10, 1): False,
            date(2026, 10, 2): False,
            date(2026, 10, 3): False,
            date(2026, 10, 4): False,
            date(2026, 10, 5): False,
            date(2026, 10, 6): False,
            date(2026, 10, 7): False,
            date(2026, 10, 8): True,
        }
    )

    decision = decide_ctp_product_session([_session("21:00", "02:30")], now=now, calendar_is_open=calendar)

    assert decision.allowed is False
    assert decision.reason_code == "CTP.SESSION.CLOSED"


def test_night_session_fails_closed_when_next_trading_day_is_unavailable() -> None:
    now = datetime(2026, 8, 24, 21, 29, tzinfo=_SHANGHAI)
    calendar = _calendar({date(2026, 8, 24): True})

    decision = decide_ctp_product_session([_session("21:00", "02:30")], now=now, calendar_is_open=calendar)

    assert decision.allowed is False
    assert decision.reason_code == "CTP.SESSION.CALENDAR_UNAVAILABLE"


def test_static_futures_table_has_expected_coverage_and_excludes_dead_keys() -> None:
    assert len(CTP_PRODUCT_SESSIONS) == 88
    assert {exchange_id for exchange_id, _ in CTP_PRODUCT_SESSIONS} == {
        "CFFEX",
        "CZCE",
        "DCE",
        "GFEX",
        "INE",
        "SHFE",
    }
    assert not {("DCE", product_id) for product_id in ("l_f", "pp_f", "v_f")} & CTP_PRODUCT_SESSIONS.keys()
    assert [(session.time_begin, session.time_end) for session in get_ctp_product_sessions("SHFE", "ag")][0] == (
        time(21),
        time(2, 30),
    )
    assert not get_ctp_product_sessions("SHFE", "ag_o")


@pytest.mark.parametrize(
    ("sessions", "calendar", "expected_reason"),
    [
        ([], _calendar(_open_days(date(2026, 8, 25))), "CTP.SESSION.NO_SESSION_TABLE"),
        ([_session("09:00", "10:15")], lambda _day: None, "CTP.SESSION.CALENDAR_UNAVAILABLE"),
    ],
)
def test_product_session_fails_closed_when_required_local_data_is_unavailable(
    sessions: list[CtpProductSession], calendar: object, expected_reason: str
) -> None:
    now = datetime(2026, 8, 25, 9, 30, tzinfo=_SHANGHAI)

    decision = decide_ctp_product_session(sessions, now=now, calendar_is_open=calendar)  # type: ignore[arg-type]

    assert decision.allowed is False
    assert decision.reason_code == expected_reason

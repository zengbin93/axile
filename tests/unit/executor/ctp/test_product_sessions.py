"""CTP 品种级交易时段判定测试。"""

from __future__ import annotations

from datetime import datetime, time
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
    decision = decide_ctp_product_session(sessions, now=moment)

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
    decision = decide_ctp_product_session(sessions, now=now)

    assert decision.allowed is expected
    assert decision.reason_code == (None if expected else "CTP.SESSION.CLOSED")
    assert product_id


@pytest.mark.parametrize("day", [22, 23, 24])
def test_product_session_decision_is_independent_of_calendar_date(day: int) -> None:
    now = datetime(2026, 8, day, 21, 29, tzinfo=_SHANGHAI)
    decision = decide_ctp_product_session([_session("21:00", "02:30")], now=now)
    assert decision.allowed is True


def test_static_futures_table_has_expected_coverage() -> None:
    assert len(CTP_PRODUCT_SESSIONS) == 91
    assert {exchange_id for exchange_id, _ in CTP_PRODUCT_SESSIONS} == {
        "CFFEX",
        "CZCE",
        "DCE",
        "GFEX",
        "INE",
        "SHFE",
    }
    assert {
        ("DCE", "l_f"),
        ("DCE", "pp_f"),
        ("DCE", "v_f"),
    } <= CTP_PRODUCT_SESSIONS.keys()
    assert [(session.time_begin, session.time_end) for session in get_ctp_product_sessions("SHFE", "ag")][0] == (
        time(21),
        time(2, 30),
    )
    assert not get_ctp_product_sessions("SHFE", "ag_o")
    assert [(session.time_begin, session.time_end) for session in get_ctp_product_sessions("DCE", "l_f")] == [
        (time(21), time(23)),
        (time(9), time(10, 15)),
        (time(10, 30), time(11, 30)),
        (time(13, 30), time(15)),
    ]
    assert [(session.time_begin, session.time_end) for session in get_ctp_product_sessions("DCE", "pp_f")] == [
        (time(21), time(23)),
        (time(9), time(10, 15)),
        (time(10, 30), time(11, 30)),
        (time(13, 30), time(15)),
    ]
    assert [(session.time_begin, session.time_end) for session in get_ctp_product_sessions("DCE", "v_f")] == [
        (time(9), time(10, 15)),
        (time(10, 30), time(11, 30)),
        (time(13, 30), time(15)),
    ]


def test_product_session_fails_closed_without_static_session_data() -> None:
    now = datetime(2026, 8, 25, 9, 30, tzinfo=_SHANGHAI)
    decision = decide_ctp_product_session([], now=now)
    assert decision.allowed is False
    assert decision.reason_code == "CTP.SESSION.NO_SESSION_TABLE"

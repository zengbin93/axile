"""CTP 合约对应品种的本地交易时段判定。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from axile.executor.china_futures_session import is_regular_night_session_transition


@dataclass(frozen=True)
class CtpProductSession:
    """一条已校验的 CTP 品种时段记录。"""

    exchange_id: str
    product_id: str
    segment_no: int
    time_begin: time
    time_end: time


@dataclass(frozen=True)
class CtpProductSessionDecision:
    """单个 CTP 品种的时段准入结论。"""

    allowed: bool
    reason_code: str | None = None


def decide_ctp_product_session(
    sessions: Sequence[CtpProductSession],
    *,
    now: datetime,
    calendar_is_open: Callable[[date], bool | None],
) -> CtpProductSessionDecision:
    """按品种时段和本地交易日历判断当前时刻是否允许报单。"""
    if not sessions:
        return CtpProductSessionDecision(False, "CTP.SESSION.SNAPSHOT_MISSING")

    current_time = now.timetz().replace(tzinfo=None)
    session = next((item for item in sessions if _contains(item, current_time)), None)
    if session is None:
        return CtpProductSessionDecision(False, "CTP.SESSION.CLOSED")

    try:
        if _is_night_session(session):
            return _decide_night_session(session, now.date(), current_time, calendar_is_open)
        return _decision_from_calendar(calendar_is_open(now.date()))
    except Exception:  # noqa: BLE001 - 本地日历读错时必须拒绝 CTP 报单
        return CtpProductSessionDecision(False, "CTP.SESSION.CALENDAR_UNAVAILABLE")


def _contains(session: CtpProductSession, current_time: time) -> bool:
    if session.time_end > session.time_begin:
        return session.time_begin <= current_time < session.time_end
    return current_time >= session.time_begin or current_time < session.time_end


def _is_night_session(session: CtpProductSession) -> bool:
    return session.time_begin >= time(17) or session.time_end < session.time_begin


def _decide_night_session(
    session: CtpProductSession,
    current_day: date,
    current_time: time,
    calendar_is_open: Callable[[date], bool | None],
) -> CtpProductSessionDecision:
    session_start_day = current_day - timedelta(days=1) if current_time < time(3) else current_day
    if calendar_is_open(session_start_day) is not True:
        return _decision_from_calendar(calendar_is_open(session_start_day))

    trading_day = _next_open_day(session_start_day, calendar_is_open)
    if trading_day is None:
        return CtpProductSessionDecision(False, "CTP.SESSION.CALENDAR_UNAVAILABLE")
    if not is_regular_night_session_transition(session_start_day, trading_day):
        return CtpProductSessionDecision(False, "CTP.SESSION.CLOSED")
    return CtpProductSessionDecision(True)


def _next_open_day(session_start_day: date, calendar_is_open: Callable[[date], bool | None]) -> date | None:
    for offset in range(1, 15):
        candidate = session_start_day + timedelta(days=offset)
        state = calendar_is_open(candidate)
        if state is None:
            return None
        if state:
            return candidate
    return None


def _decision_from_calendar(is_open: bool | None) -> CtpProductSessionDecision:
    if is_open is None:
        return CtpProductSessionDecision(False, "CTP.SESSION.CALENDAR_UNAVAILABLE")
    if not is_open:
        return CtpProductSessionDecision(False, "CTP.SESSION.CLOSED")
    return CtpProductSessionDecision(True)


__all__ = ["CtpProductSession", "CtpProductSessionDecision", "decide_ctp_product_session"]

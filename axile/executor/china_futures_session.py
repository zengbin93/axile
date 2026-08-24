"""中国期货日夜盘之间的交易日转换规则。"""

from __future__ import annotations

from datetime import date, timedelta


def is_regular_night_session_transition(session_start_day: date, trading_day: date) -> bool:
    """判断自然日晚盘能否归入给定的下一个交易日。"""
    if trading_day == session_start_day + timedelta(days=1):
        return True
    return session_start_day.weekday() == 4 and trading_day == session_start_day + timedelta(days=3)


__all__ = ["is_regular_night_session_transition"]

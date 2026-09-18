"""中国期货日夜盘之间的交易日转换与整市场可撮合窗。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from axile.channels.schedule_clock import CN_FUTURES_WINDOWS, is_within_schedule_windows


def is_regular_night_session_transition(session_start_day: date, trading_day: date) -> bool:
    """判断自然日晚盘能否归入给定的下一个交易日。"""
    if trading_day == session_start_day + timedelta(days=1):
        return True
    return session_start_day.weekday() == 4 and trading_day == session_start_day + timedelta(days=3)


def is_within_possible_china_futures_session(now: datetime) -> bool:
    """判断此刻是否可能存在可交易的中国期货品种.

    日盘 ``09:00–11:30`` / ``13:00–15:15``（含国债多出的 15 分钟），夜盘
    ``21:00–02:30``。午休 ``11:30–13:00`` 与日夜盘缝全市场都不可下单。

    这是渠道级保守预检，不是完整交易日历：交易日由服务端日历判断，窗口内具体
    品种是否开盘仍由 CTP/TQ 品种时段表判断。09:00–09:30 商品已开、股指未开；
    15:00–15:15 仅国债；10:15–10:30 茶歇仅商品停、股指仍开。无时区的
    ``datetime`` 按上海时间理解。
    """
    return is_within_schedule_windows(now, CN_FUTURES_WINDOWS)


__all__ = ["is_regular_night_session_transition", "is_within_possible_china_futures_session"]

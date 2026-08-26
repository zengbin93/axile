"""中国期货日夜盘之间的交易日转换与整市场可撮合窗。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DAY_OPEN = time(9, 0)
_DAY_CLOSE = time(15, 15)
_NIGHT_OPEN = time(21, 0)
_NIGHT_CLOSE = time(2, 30)


def is_regular_night_session_transition(session_start_day: date, trading_day: date) -> bool:
    """判断自然日晚盘能否归入给定的下一个交易日。"""
    if trading_day == session_start_day + timedelta(days=1):
        return True
    return session_start_day.weekday() == 4 and trading_day == session_start_day + timedelta(days=3)


def is_within_possible_china_futures_session(now: datetime) -> bool:
    """判断此刻是否可能存在可交易的中国期货品种.

    日盘 ``09:00 <= t < 15:15``（含国债多出的 15 分钟），夜盘 ``21:00 <= t`` 或
    ``t < 02:30``。其余为日夜盘缝，全市场没有任何品种可下单。

    这是渠道级保守预检，不是完整交易日历：交易日由服务端日历判断，窗口内具体
    品种是否开盘仍由 CTP/TQ 品种时段表判断。09:00–09:30 商品已开、股指未开；
    15:00–15:15 仅国债。无时区的 ``datetime`` 按上海时间理解。
    """
    local = now.astimezone(_SHANGHAI) if now.tzinfo is not None else now.replace(tzinfo=_SHANGHAI)
    clock = local.timetz().replace(tzinfo=None)
    if _DAY_OPEN <= clock < _DAY_CLOSE:
        return True
    return clock >= _NIGHT_OPEN or clock < _NIGHT_CLOSE


__all__ = ["is_regular_night_session_transition", "is_within_possible_china_futures_session"]

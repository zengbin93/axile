"""TqSdk 合约级交易时段判定。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_QUOTE_UNAVAILABLE = "TqSdk 合约交易时段不可用"
_CALENDAR_UNAVAILABLE = "TqSdk 交易日历不可用"


class TQTradingTimeApi(Protocol):
    """判定所需的最小 TqApi 协议。"""

    def get_quote(self, symbol: str) -> object:
        """返回已加载交易时段元数据的合约行情对象。"""

    def get_trading_calendar(self, start_dt: date, end_dt: date) -> object:
        """返回指定自然日范围的 TqSdk 交易日历。"""


@dataclass(frozen=True, slots=True)
class TQTradingTimeDecision:
    """单个 TqSdk 合约的交易时段判定结果。"""

    available: bool
    reason: str | None = None


class _QuoteTradingTimeUnavailable(ValueError):
    """合约时段元数据未就绪或格式无效。"""


class _TradingCalendarUnavailable(ValueError):
    """交易日历未就绪或格式无效。"""


def _parse_clock(value: object) -> int:
    """将 TqSdk ``HH:MM:SS`` 时刻转换为距交易日零点的秒数。"""
    if not isinstance(value, str) or len(value) != 8 or value[2] != ":" or value[5] != ":":
        raise _QuoteTradingTimeUnavailable("交易时段格式无效")
    try:
        hour, minute, second = (int(part) for part in value.split(":"))
    except ValueError as exc:
        raise _QuoteTradingTimeUnavailable("交易时段格式无效") from exc
    if not 0 <= hour <= 47 or not 0 <= minute < 60 or not 0 <= second < 60:
        raise _QuoteTradingTimeUnavailable("交易时段超出范围")
    return hour * 3600 + minute * 60 + second


def _contains(moment: int, ranges: Iterable[object]) -> bool:
    """按左闭右开区间判断秒数是否在任一 TqSdk 时段内。"""
    contains = False
    for item in ranges:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise _QuoteTradingTimeUnavailable("交易时段记录无效")
        begin, end = (_parse_clock(value) for value in item)
        if begin >= end:
            raise _QuoteTradingTimeUnavailable("交易时段起止无效")
        contains = contains or begin <= moment < end
    return contains


def _calendar_days(calendar: object) -> dict[date, bool]:
    """将 TqSdk 日历结果转换为日期到交易日状态的映射。"""
    records = getattr(calendar, "to_dict", None)
    if not callable(records):
        raise _TradingCalendarUnavailable("交易日历格式无效")
    try:
        rows = records("records")
    except Exception as exc:  # noqa: BLE001 - 外部 DataFrame 适配失败必须 fail-closed
        raise _TradingCalendarUnavailable("交易日历记录无效") from exc
    if not isinstance(rows, list):
        raise _TradingCalendarUnavailable("交易日历记录无效")

    by_day: dict[date, bool] = {}
    for row in rows:
        if not isinstance(row, Mapping) or "date" not in row or "trading" not in row:
            continue
        raw_day = row["date"]
        day = raw_day.date() if isinstance(raw_day, datetime) else raw_day
        if isinstance(day, date):
            by_day[day] = bool(row["trading"])
    return by_day


def _is_trading_day(calendar: object, target: date) -> bool:
    """从 TqSdk 日历结果中读取指定日期的交易日状态。"""
    by_day = _calendar_days(calendar)
    if target not in by_day:
        raise _TradingCalendarUnavailable(f"交易日历缺少 {target.isoformat()}")
    return by_day[target]


def _night_session_is_open(api: TQTradingTimeApi, session_day: date) -> bool:
    """按 TqSdk 日历判断夜盘起始日及其后交易日是否构成有效夜盘。"""
    try:
        calendar = api.get_trading_calendar(session_day, session_day + timedelta(days=14))
    except Exception as exc:  # noqa: BLE001 - TqSdk 外部 API 失败必须 fail-closed
        raise _TradingCalendarUnavailable("无法读取交易日历") from exc
    by_day = _calendar_days(calendar)
    if by_day.get(session_day) is not True:
        return False

    next_trading_day = next((day for day in sorted(by_day) if day > session_day and by_day[day]), None)
    if next_trading_day is None:
        raise _TradingCalendarUnavailable("交易日历未返回后续交易日")
    return next_trading_day == session_day + timedelta(days=1)


def _trading_time_ranges(quote: object, name: str) -> list[object]:
    trading_time = getattr(quote, "trading_time", None)
    ranges = getattr(trading_time, name, None)
    if not isinstance(ranges, list):
        raise _QuoteTradingTimeUnavailable(f"合约交易时段 {name} 不可用")
    return ranges


def check_tq_trading_time(
    api: TQTradingTimeApi,
    symbol: str,
    *,
    now: datetime | None = None,
) -> TQTradingTimeDecision:
    """根据 TqSdk 合约元数据与交易日历判定该合约当前能否交易。"""
    current = (now or datetime.now(_SHANGHAI)).astimezone(_SHANGHAI)
    try:
        quote = api.get_quote(symbol)
        day_ranges = _trading_time_ranges(quote, "day")
        night_ranges = _trading_time_ranges(quote, "night")
        if not day_ranges and not night_ranges:
            raise _QuoteTradingTimeUnavailable("合约未返回交易时段")
        seconds = current.hour * 3600 + current.minute * 60 + current.second

        in_day_session = _contains(seconds, day_ranges)
        in_night_session = _contains(seconds, night_ranges)
        in_previous_night_session = _contains(seconds + 24 * 3600, night_ranges)
        if in_day_session:
            try:
                calendar = api.get_trading_calendar(current.date(), current.date())
                is_trading_day = _is_trading_day(calendar, current.date())
            except _TradingCalendarUnavailable:
                return TQTradingTimeDecision(available=False, reason=_CALENDAR_UNAVAILABLE)
            except Exception:  # noqa: BLE001 - TqSdk 外部 API 失败必须 fail-closed
                return TQTradingTimeDecision(available=False, reason=_CALENDAR_UNAVAILABLE)
            if is_trading_day:
                return TQTradingTimeDecision(available=True)
            return TQTradingTimeDecision(available=False, reason="当前不是 TqSdk 交易日")

        if in_night_session:
            session_day = current.date()
        elif in_previous_night_session:
            session_day = current.date() - timedelta(days=1)
        else:
            session_day = None
        if session_day is not None:
            try:
                is_open = _night_session_is_open(api, session_day)
            except _TradingCalendarUnavailable:
                return TQTradingTimeDecision(available=False, reason=_CALENDAR_UNAVAILABLE)
            if is_open:
                return TQTradingTimeDecision(available=True)
            return TQTradingTimeDecision(available=False, reason="当前夜盘对应交易日无效")

        return TQTradingTimeDecision(available=False, reason="当前不在该合约的 TqSdk 交易时段")
    except _QuoteTradingTimeUnavailable:
        return TQTradingTimeDecision(available=False, reason=_QUOTE_UNAVAILABLE)
    except Exception:  # noqa: BLE001 - TqSdk 时段读取失败必须 fail-closed
        return TQTradingTimeDecision(available=False, reason=_QUOTE_UNAVAILABLE)


__all__ = ["TQTradingTimeApi", "TQTradingTimeDecision", "check_tq_trading_time"]

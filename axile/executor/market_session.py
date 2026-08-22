"""公共市场交易日判断工具。"""

from __future__ import annotations

from datetime import date, datetime


def is_china_futures_trading_day(value: date | datetime | None = None) -> bool:
    """判断日期是否为中国期货的常规工作日。

    Notes
    -----
    节假日停市由柜台最终校验；公共层这里只做不依赖渠道 SDK 的周末过滤。
    """
    current = value.date() if isinstance(value, datetime) else value or date.today()
    return current.weekday() < 5


__all__ = ["is_china_futures_trading_day"]

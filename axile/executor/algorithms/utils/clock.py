"""
时钟抽象模块.

提供统一的时钟接口，支持真实时钟和仿真时钟。
算法代码通过 Clock 接口获取时间和等待，在仿真环境下可以自动加速。
"""

import threading
import time
from datetime import datetime, tzinfo
from typing import Protocol


class Clock(Protocol):
    """
    时钟协议.

    定义时间相关操作的统一接口。生产环境使用 ``RealClock``，
    仿真环境使用 ``SimulatedClock``。
    """

    def time(self) -> float:
        """
        获取当前时间戳.

        Returns
        -------
        float
            当前 Unix 时间戳，单位为秒。
        """
        ...

    def sleep(self, seconds: float) -> None:
        """
        等待指定秒数.

        Parameters
        ----------
        seconds : float
            需要等待的秒数。
        """
        ...

    def event_wait(self, event: threading.Event, timeout: float) -> bool:
        """
        等待事件触发或超时.

        Returns
        -------
        bool
            事件已触发时返回 ``True``，超时时返回 ``False``。

        Parameters
        ----------
        event : threading.Event
            要等待的事件对象。
        timeout : float
            最大等待时长，单位为秒。
        """
        ...


class RealClock:
    """
    真实时钟.

    使用系统时间和真实等待，用于生产环境。
    """

    def time(self) -> float:
        """
        获取当前时间戳.

        Returns
        -------
        float
            当前 Unix 时间戳，单位为秒。
        """
        return time.time()

    def sleep(self, seconds: float) -> None:
        """
        等待指定秒数.

        Parameters
        ----------
        seconds : float
            需要等待的秒数。
        """
        time.sleep(seconds)

    def event_wait(self, event: threading.Event, timeout: float) -> bool:
        """
        等待事件触发或超时.

        Returns
        -------
        bool
            事件已触发时返回 ``True``，超时时返回 ``False``。

        Parameters
        ----------
        event : threading.Event
            要等待的事件对象。
        timeout : float
            最大等待时长，单位为秒。
        """
        return event.wait(timeout=timeout)


# 全局默认时钟
_default_clock: Clock = RealClock()


def _resolve_clock(clock: Clock | None = None) -> Clock:
    """
    解析要使用的时钟实例.

    Parameters
    ----------
    clock : Clock | None, optional
        显式传入的时钟；为空时使用全局默认时钟。

    Returns
    -------
    Clock
        解析后的时钟实例。
    """
    return get_default_clock() if clock is None else clock


def get_default_clock() -> Clock:
    """
    获取默认时钟.

    Returns
    -------
    Clock
        当前设置的默认时钟实例。
    """
    return _default_clock


def set_default_clock(clock: Clock) -> None:
    """
    设置默认时钟.

    Parameters
    ----------
    clock : Clock
        要设置的时钟实例。
    """
    global _default_clock
    _default_clock = clock


def clock_now(clock: Clock | None = None, tz: tzinfo | None = None) -> datetime:
    """
    读取当前 ``datetime``.

    Parameters
    ----------
    clock : Clock | None, optional
        显式传入的时钟；为空时使用全局默认时钟。
    tz : tzinfo | None, optional
        目标时区；为空时返回本地时区语义下的 ``datetime``。

    Returns
    -------
    datetime
        基于当前时钟时间戳转换得到的时间对象。
    """
    current_ts = _resolve_clock(clock).time()
    if tz is None:
        return datetime.fromtimestamp(current_ts)
    return datetime.fromtimestamp(current_ts, tz=tz)


def clock_now_iso(clock: Clock | None = None, tz: tzinfo | None = None) -> str:
    """
    读取当前 ISO 格式时间字符串.

    Parameters
    ----------
    clock : Clock | None, optional
        显式传入的时钟；为空时使用全局默认时钟。
    tz : tzinfo | None, optional
        目标时区；为空时返回本地时区语义下的字符串。

    Returns
    -------
    str
        当前时间对应的 ISO 8601 字符串。
    """
    return clock_now(clock=clock, tz=tz).isoformat()


def clock_now_ms(clock: Clock | None = None) -> int:
    """
    读取当前毫秒时间戳.

    Parameters
    ----------
    clock : Clock | None, optional
        显式传入的时钟；为空时使用全局默认时钟。

    Returns
    -------
    int
        当前 Unix 时间戳，单位为毫秒。
    """
    return int(_resolve_clock(clock).time() * 1_000)

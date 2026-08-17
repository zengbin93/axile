"""``CtpTrader`` 拆分后共享的常量、数据类、异常与底层工具.

此前位于 ``axile/executor/ctp/core/trader.py`` 顶部的模块级定义全部迁移到这里。
mixin 与主类都从本模块导入。
"""

# _LazySymbolProxy 让 CThostFtdcTraderApi 等类型在静态分析里是 object，
# _safe_release_trader_api 会触发 reportInvalidTypeForm；
# _ClockProtocol 是 duck-typed 的非 Protocol 占位类，导致 get_default_clock
# 的返回类型与 Clock / _FallbackClock 不匹配触发 reportReturnType。
# 二者均与本模块的兼容性策略相关，故抑制。
# pyright: reportInvalidTypeForm=false
# pyright: reportReturnType=false

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum

from axile.executor.account_control.registry import (
    RegisteredThrottleGroup,
    get_default_account_control_registry,
    register_default_registry_bootstrap,
)
from axile.executor.ctp.core.openctp_compat import CThostFtdcTraderApi


class _ClockProtocol:
    """最小时钟协议."""

    def time(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def event_wait(self, event: threading.Event, timeout: float) -> bool: ...


def get_default_clock() -> _ClockProtocol:
    """返回默认时钟实现.

    优先复用统一时钟，测试可通过猴子补丁替换该函数。
    """

    class _FallbackClock:
        def time(self) -> float:
            return time.time()

        def sleep(self, _seconds: float) -> None:
            time.sleep(_seconds)

        def event_wait(self, event: threading.Event, _timeout: float) -> bool:
            return event.wait(_timeout)

    try:
        from axile.executor.algorithms.utils import get_default_clock as _utils_get_default_clock

        return _utils_get_default_clock()
    except Exception:
        return _FallbackClock()


CTP_TD_GLOBAL_GROUP = "ctp_td_global"


def _ensure_ctp_td_global_group_registered() -> None:
    registry = get_default_account_control_registry()
    expected_group = RegisteredThrottleGroup(
        key=CTP_TD_GLOBAL_GROUP,
    )
    if registry.is_frozen:
        existing = registry.get_group(CTP_TD_GLOBAL_GROUP)
        if existing is None:
            return
        if existing != expected_group:
            raise ValueError(f"group key `{CTP_TD_GLOBAL_GROUP}` definition conflict")
        return
    registry.register_group(
        CTP_TD_GLOBAL_GROUP,
    )


_ensure_ctp_td_global_group_registered()
register_default_registry_bootstrap(_ensure_ctp_td_global_group_registered)


class ConnectionStatus(Enum):
    """连接状态枚举."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    LOGGED_IN = "logged_in"
    READY = "ready"  # 结算确认完成，可以交易


@dataclass
class RiskControlConfig:
    """风控配置."""

    # 操作次数阈值设置
    max_queries_per_minute: int = 60  # 每分钟最大查询次数
    max_orders_per_minute: int = 30  # 每分钟最大委托次数
    # 撤单频率当前不单独统计，沿用统一操作频率控制

    # 报单数量异常处理
    min_order_volume: int = 1  # 最小委托手数
    max_order_volume: int = 100  # 最大委托手数
    max_total_position: int = 1000  # 最大总持仓手数

    # 报单速率异常处理
    min_order_interval: float = 0.5  # 最小报单间隔（秒）
    max_orders_per_second: int = 5  # 每秒最大报单数

    # 报单价格异常处理
    max_price_deviation: float = 0.05  # 最大价格偏离度（5%）
    enable_limit_price_check: bool = True  # 是否启用涨跌停检查
    enable_tick_size_check: bool = True  # 是否启用最小变动价位检查


@dataclass
class OperationCounter:
    """操作计数器."""

    timestamp: float
    operation_type: str  # 'query', 'order' (cancel已删除)


class CtpTimeoutError(TimeoutError):
    """当 CTP 操作超出超时时间时抛出."""


class CtpCancelledError(RuntimeError):
    """当 CTP 操作在关闭过程中被取消时抛出."""


class CtpStateError(RuntimeError):
    """当 CTP 连接状态未达到预期阶段时抛出."""


def _wait_or_raise(
    event: threading.Event,
    timeout: float,
    message: str,
    *,
    stop_event: threading.Event | None = None,
    poll_interval: float = 0.1,
) -> None:
    """等待事件完成，否则抛出语义化超时异常."""
    clock = get_default_clock()
    deadline = clock.time() + timeout

    while True:
        if stop_event and stop_event.is_set():
            raise CtpCancelledError(f"{message}，已收到停止请求")

        remaining = deadline - clock.time()
        if remaining <= 0:
            raise CtpTimeoutError(message)

        wait_timeout = min(remaining, poll_interval)
        if clock.event_wait(event, wait_timeout):
            if stop_event and stop_event.is_set():
                raise CtpCancelledError(f"{message}，已收到停止请求")
            return


def _safe_release_trader_api(api: CThostFtdcTraderApi | None) -> None:
    """按照 OpenCTP 示例要求的关闭顺序释放交易 API 实例."""
    if api is None:
        return

    try:
        api.RegisterSpi(None)
    except (AttributeError, OSError, RuntimeError):
        pass

    try:
        api.Release()
    except (AttributeError, OSError, RuntimeError):
        return


def _safe_decode_content(content: str | bytes | None) -> str:
    """
    安全解码CTP内容，处理各种编码问题.

    Parameters
    ----------
    content : str | bytes | None
        可能是 ``str``、``bytes`` 或 ``None`` 的内容。

    Returns
    -------
    str
        解码后的字符串内容。
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    # 此时 content 必定为 bytes 类型
    # 尝试多种编码方式
    for encoding in ["gbk", "utf-8", "gb2312", "latin-1"]:
        try:
            return content.decode(encoding, errors="ignore")
        except (UnicodeDecodeError, LookupError):
            continue

    # 最后的备用方案
    return content.decode("latin-1", errors="ignore")

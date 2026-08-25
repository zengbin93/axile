"""定义 Axile 运行时日志使用的稳定业务组件标签."""

from enum import StrEnum
from typing import Any


class LogComponent(StrEnum):
    """控制台与结构化日志共享的业务组件."""

    SYSTEM = "系统"
    SERVICE = "服务"
    API = "接口"
    EXECUTION = "执行"
    WORKER = "任务"
    SCHEDULER = "调度"
    CALENDAR = "日历"
    AUDIT = "审计"
    ALGORITHM = "算法"
    ORDER = "订单"
    CTP = "CTP"
    GM = "掘金"
    TQ = "天勤"
    MARKET_DATA = "行情"
    NOTIFICATION = "通知"
    MANUAL = "人工"
    SIMULATION = "仿真"
    DATABASE = "数据库"
    EXTERNAL = "外部"


def bind_log_context(logger: Any, *, component: LogComponent | None = None, **context: object) -> Any:
    """为 Loguru logger 绑定业务上下文，并兼容测试中的轻量 logger."""
    values = {key: value for key, value in context.items() if value is not None}
    if component is not None:
        values["component"] = component.value
    bind = getattr(logger, "bind", None)
    return bind(**values) if callable(bind) else logger

"""为 Axile 服务端配置 Loguru sink 与日志拦截.

参考:
- https://github.com/MatthewScholefield/loguru-logging-intercept/blob/main/loguru_logging_intercept.py
- https://github.com/MatthewScholefield/uvicorn-loguru-integration/blob/main/uvicorn_loguru_integration.py.
"""

import json
import logging
import sys
import traceback
from types import FrameType
from typing import Any, cast

from loguru import logger

from axile.common.config import settings
from axile.common.logging import LogComponent
from axile.common.trade_channel import TradeChannel


class InterceptHandler(logging.Handler):
    """将标准库 logging 日志转发到 Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        """把标准库日志记录转发到 Loguru."""
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        frame, depth = logging.currentframe(), 1
        while frame.f_code.co_filename in (logging.__file__, __file__):  # noqa: WPS609
            frame = cast("FrameType", frame.f_back)
            depth += 1

        logger_with_opts = logger.opt(depth=depth, exception=record.exc_info)
        try:
            logger_with_opts.log(level, "{}", record.getMessage())
        except Exception as e:
            safe_msg = getattr(record, "msg", None) or str(record)
            logger_with_opts.warning(
                "Exception logging the following native logger message: {}, {!r}",
                safe_msg,
                e,
            )


LOGGING_MODULES = (
    "",
    "uvicorn.error",
    "uvicorn.access",
    "sqlalchemy.engine.Engine",
)

MODULE_LOG_LEVELS = {
    "asyncio": logging.WARNING,
    "threading": logging.WARNING,
    "urllib3": logging.WARNING,
    "uvicorn.access": logging.WARNING,
    "starlette.middleware.errors": logging.WARNING,
    "sqlalchemy": logging.WARNING,
    "sqlalchemy.engine.Engine": logging.WARNING,
    "sqlalchemy.pool": logging.WARNING,
    "aiosqlite": logging.WARNING,
}

SUPPRESSED_INFO_LOGGERS = {
    "uvicorn.access",
    "starlette.middleware.errors",
}


def setup_loguru_logging_intercept(level: int = logging.DEBUG) -> None:
    """让选定的标准库 logger 走统一的 Loguru sink."""
    logging.basicConfig(handlers=[InterceptHandler()], level=level)  # noqa
    for logger_name in LOGGING_MODULES:
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler(level=level)]
        mod_logger.propagate = False

    for logger_name, logger_level in MODULE_LOG_LEVELS.items():
        logging.getLogger(logger_name).setLevel(logger_level)


_CONTEXT_FIELDS = (
    "account_id",
    "account_name",
    "channel",
    "execution_id",
    "symbol",
    "algorithm",
    "trigger_source",
    "calendar_id",
    "calendar_day",
)

# 规则按具体到宽泛排列。显式 ``component`` 始终优先于这里的源码归类。
_COMPONENT_PREFIXES: tuple[tuple[str, LogComponent], ...] = (
    ("axile.executor.algorithms.utils.order_", LogComponent.ORDER),
    ("axile.executor.algorithms", LogComponent.ALGORITHM),
    ("axile.executor.ctp", LogComponent.CTP),
    ("axile.server.execution.ctp_channels", LogComponent.CTP),
    ("axile.executor.gm", LogComponent.GM),
    ("axile.executor.tq", LogComponent.TQ),
    ("axile.server.api", LogComponent.API),
    ("axile.server.execution.worker_backend", LogComponent.WORKER),
    ("axile.server.execution.scheduler", LogComponent.SCHEDULER),
    ("axile.server.execution_audit", LogComponent.AUDIT),
    ("axile.server.error_notifications", LogComponent.NOTIFICATION),
    ("axile.executor.feishu_notifications", LogComponent.NOTIFICATION),
    ("axile.server.human", LogComponent.MANUAL),
    ("axile.server.execution", LogComponent.EXECUTION),
    ("axile.executor.abstract_executor", LogComponent.EXECUTION),
    ("axile.executor.execution_", LogComponent.EXECUTION),
    ("axile.server", LogComponent.SYSTEM),
    ("axile.executor", LogComponent.EXECUTION),
    ("sqlalchemy", LogComponent.DATABASE),
    ("aiosqlite", LogComponent.DATABASE),
    ("apscheduler", LogComponent.SCHEDULER),
    ("uvicorn", LogComponent.SERVICE),
    ("starlette", LogComponent.SERVICE),
)


def execution_log_context(
    *,
    account_id: object | None = None,
    account_name: str | None = None,
    channel: object | None = None,
    execution_id: str | None = None,
    symbol: str | None = None,
) -> dict[str, object]:
    """
    构造执行链路日志使用的结构化上下文字段.

    Parameters
    ----------
    account_id : object | None, default=None
        账户主键，用于关联同一账户的所有日志。
    account_name : str | None, default=None
        账户名称，便于人工辨识。
    channel : object | None, default=None
        交易渠道；``TradeChannel`` 会被展开为 ``.value`` 字符串。
    execution_id : str | None, default=None
        本次执行的全局标识；填入后可 ``grep`` 出一次执行的全部日志。
    symbol : str | None, default=None
        当前单品种执行会话的交易标的。

    Returns
    -------
    dict[str, object]
        可直接传入 ``logger.contextualize`` / ``logger.bind`` 的上下文字典。
    """
    channel_value = channel.value if isinstance(channel, TradeChannel) else channel
    return {
        "account_id": account_id,
        "account_name": account_name,
        "channel": channel_value,
        "execution_id": execution_id,
        "symbol": symbol,
    }


def _level_label(level_name: str) -> str:
    return "WARN" if level_name == "WARNING" else level_name


def _component_label(name: str | None, extra: dict[str, Any]) -> str:
    """根据显式绑定或源码命名空间解析稳定业务组件."""
    explicit = extra.get("component")
    if explicit:
        return str(explicit)

    logger_name = name or ""
    for prefix, component in _COMPONENT_PREFIXES:
        if logger_name.startswith(prefix):
            return component.value
    if logger_name.startswith("axile."):
        return LogComponent.SYSTEM.value
    return LogComponent.EXTERNAL.value


def _context_label(extra: dict[str, Any]) -> str:
    """把结构化上下文渲染成紧凑的人类可读前缀."""
    parts: list[str] = []
    account_id = extra.get("account_id")
    account_name = extra.get("account_name")
    if account_name:
        account_label = str(account_name)
        if account_id is not None:
            account_label = f"{account_label}#{account_id}"
        parts.append(account_label)
    elif account_id is not None:
        parts.append(f"账户#{account_id}")
    channel = extra.get("channel")
    if channel:
        parts.append(str(channel))
    symbol = extra.get("symbol")
    if symbol:
        parts.append(str(symbol))
    execution_id = extra.get("execution_id")
    if execution_id:
        parts.append(str(execution_id)[:8])
    if not parts:
        return ""
    return f"[{' '.join(parts)}] "


def _format_record(record: dict[str, Any]) -> str:
    """生成面向人工阅读的控制台日志模板."""
    extra = record["extra"]
    extra["_lvl"] = f"{_level_label(record['level'].name):<5}"
    name = record.get("name") or record.get("module")
    extra["_component"] = _component_label(name, extra)
    extra["_ctx"] = _context_label(extra)
    return (
        "<green>{time:YYMMDD HH:mm:ss.SSS}</green> "
        "<level>{extra[_lvl]}</level> "
        "<cyan>[{extra[_component]}]</cyan> "
        "{extra[_ctx]}"
        "<level>{message}</level>\n{exception}"
    )


def _exception_payload(exception: Any) -> dict[str, str] | None:
    """把 Loguru 异常记录转换为 JSON 可序列化结构."""
    if exception is None:
        return None
    return {
        "type": exception.type.__name__,
        "message": str(exception.value),
        "traceback": "".join(traceback.format_exception(exception.type, exception.value, exception.traceback)),
    }


def _json_format_record(record: dict[str, Any]) -> str:
    """生成一行稳定、无冗余包裹的 JSONL 日志."""
    extra = record["extra"]
    name = record.get("name") or record.get("module")
    component = _component_label(name, extra)
    context = {field: extra[field] for field in _CONTEXT_FIELDS if extra.get(field) is not None}
    payload = {
        "schema_version": 1,
        "timestamp": record["time"].isoformat(timespec="milliseconds"),
        "level": record["level"].name,
        "component": component,
        "message": record["message"],
        "context": context,
        "source": {
            "name": record.get("name"),
            "file": record["file"].path,
            "function": record["function"],
            "line": record["line"],
        },
        "process": {"id": record["process"].id, "name": record["process"].name},
        "thread": {"id": record["thread"].id, "name": record["thread"].name},
        "exception": _exception_payload(record["exception"]),
    }
    extra["_json"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return "{extra[_json]}\n"


def _sink_filter(record: dict[str, Any]) -> bool:
    """过滤低价值第三方日志，保留 WARNING 及以上."""
    logger_name = record.get("name", "")
    level_no = record["level"].no
    if logger_name in SUPPRESSED_INFO_LOGGERS and level_no < logging.WARNING:
        return False
    return True


def setup_logging() -> None:
    """为当前运行环境配置控制台和文件日志."""
    if settings.environment == "local":
        console_level = logging.INFO
    else:
        # 生产用WARNING
        console_level = logging.WARNING

    # 添加控制台日志
    logger.configure(
        handlers=cast(
            "Any",
            [
                {
                    "sink": sys.stdout,
                    "format": _format_record,
                    "level": console_level,
                    "filter": _sink_filter,
                },
            ],
        ),
        extra={},
    )

    # 将标准logger转给loguru
    setup_loguru_logging_intercept()

    settings.app_log_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"目录已存在或创建完成：{settings.app_log_dir}")

    # 文件日志使用 JSON Lines，保留完整源码位置供诊断工具读取。
    logger.add(
        settings.app_log_dir / "axile.jsonl",
        format=cast("Any", _json_format_record),
        rotation=settings.axile_log_rotation,
        level=console_level,
        filter=cast("Any", _sink_filter),
        encoding="utf-8",
    )

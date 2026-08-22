"""为 Axile 服务端配置 Loguru sink 与日志拦截.

参考:
- https://github.com/MatthewScholefield/loguru-logging-intercept/blob/main/loguru_logging_intercept.py
- https://github.com/MatthewScholefield/uvicorn-loguru-integration/blob/main/uvicorn_loguru_integration.py.
"""

import logging
import sys
from types import FrameType
from typing import Any, cast

from loguru import logger

from axile.common.config import settings
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


#: ``{name}`` 列的固定宽度，用于让消息正文的起始位置对齐成一条竖线。
_NAME_WIDTH = 22


def execution_log_context(
    *,
    account_id: object | None = None,
    account_name: str | None = None,
    channel: object | None = None,
    execution_id: str | None = None,
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
    }


def _level_label(level_name: str) -> str:
    return "WARN" if level_name == "WARNING" else level_name


def _short_name(name: str | None) -> str:
    """
    将全限定 logger 名收窄为末两段，去掉喧宾夺主的 ``axile.`` 前缀.

    Parameters
    ----------
    name : str | None
        Loguru record 中的 logger 名。脚本被动态执行（``compile(..., "<string>",
        "exec")``）时，调用帧缺少 ``__name__``，Loguru 会填入 ``None``。

    Returns
    -------
    str
        收窄后的 logger 名；``name`` 为空或 ``None`` 时返回 ``"<unknown>"``。
    """
    if not name:
        return "<unknown>"
    parts = name.split(".")
    tail = ".".join(parts[-2:]) if len(parts) > 2 else name
    if len(tail) > _NAME_WIDTH:
        tail = "…" + tail[-(_NAME_WIDTH - 1) :]
    return tail


def _context_label(extra: dict[str, Any]) -> str:
    """把结构化上下文渲染成紧凑前缀，如 ``[1 模拟账户 ctp 0e7a80e9] ``."""
    parts: list[str] = []
    account_id = extra.get("account_id")
    if account_id is not None:
        parts.append(str(account_id))
    account_name = extra.get("account_name")
    if account_name:
        parts.append(str(account_name))
    channel = extra.get("channel")
    if channel:
        parts.append(str(channel))
    execution_id = extra.get("execution_id")
    if execution_id:
        parts.append(str(execution_id)[:8])
    if not parts:
        return ""
    return f"[{' '.join(parts)}] "


def _format_record(record: dict[str, Any]) -> str:
    extra = record["extra"]
    extra["_lvl"] = f"{_level_label(record['level'].name):<5}"
    name = record.get("name") or record.get("module")
    extra["_name"] = f"{_short_name(name):<{_NAME_WIDTH}}"
    extra["_ctx"] = _context_label(extra)
    return (
        "<green>{time:YYMMDD HH:mm:ss.SSS}</green> "
        "<level>{extra[_lvl]}</level> "
        "<cyan>{extra[_name]}</cyan> "
        "{extra[_ctx]}"
        "<level>{message}</level>\n"
    )


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

    # 添加文件日志, 日志级别会比控制台小一级
    logger.add(
        settings.app_log_dir / "axile.log",
        format=cast("Any", _format_record),
        rotation=settings.axile_log_rotation,
        level=console_level,
        filter=cast("Any", _sink_filter),
    )

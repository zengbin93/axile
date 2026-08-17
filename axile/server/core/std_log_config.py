"""第三方 logger 使用的标准库 logging 配置辅助函数."""

import logging.config


def setup_std_logging() -> dict[str, object]:
    """设置标准日志配置, 用于格式化 sqlalchemy/root/uvicorn 的标准日志."""
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
            "sqlalchemy.engine.Engine": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.server": {
                "level": "WARNING",
                "handlers": ["default"],
                "propagate": False,
            },
        },
        "root": {"level": "WARN", "handlers": ["default"], "propagate": False},
    }

    logging.config.dictConfig(log_config)
    return log_config

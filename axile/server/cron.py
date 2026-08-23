"""CRON 表达式解析辅助函数."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]

SCHEDULER_TIMEZONE = ZoneInfo("Asia/Shanghai")


def is_blank_cron_expr(cron_expr: str | None) -> bool:
    """
    判断 cron 是否视为「无排程」（仅手动 / 外接触发）.

    前端关闭「自动调仓」时会把 ``cron_expr`` 写成空串；空串合法且表示不建调度任务，
    不得再交给 :func:`parse_cron_expr`（其会抛「空表达式」）。

    Parameters
    ----------
    cron_expr : str | None
        账户上存储的表达式；``None`` 或仅空白均视为无排程。

    Returns
    -------
    bool
        为真时应跳过调度解析与建 job。
    """
    return cron_expr is None or not str(cron_expr).strip()


def parse_cron_expr(cron_expr: str) -> list[CronTrigger]:
    """
    解析一个或多个 CRON 表达式.

    Parameters
    ----------
    cron_expr : str
        使用 ``|`` 分隔的单个或多个 crontab 表达式。

    Returns
    -------
    list[CronTrigger]
        解析后的 APScheduler CRON 触发器列表。

    Raises
    ------
    ValueError
        当表达式为空或任一子表达式无法解析时抛出。
        无排程场景请先用 :func:`is_blank_cron_expr` 短路，不要调用本函数。
    """
    if is_blank_cron_expr(cron_expr):
        raise ValueError("空表达式")

    try:
        cron_parts = [ce.strip() for ce in cron_expr.split("|") if ce.strip()]
        if not cron_parts:
            raise ValueError("空表达式")
        return [CronTrigger.from_crontab(ce, timezone=SCHEDULER_TIMEZONE) for ce in cron_parts]  # type: ignore[misc]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"解析CRON表达式失败: {exc}") from exc

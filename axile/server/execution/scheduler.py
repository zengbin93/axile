"""账户执行任务的调度辅助函数."""

from datetime import datetime
from typing import Union, cast

import loguru
from apscheduler.job import Job  # type: ignore[import-not-found]
from apscheduler.triggers.combining import OrTrigger  # type: ignore[import-not-found]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]

from axile.server.core.db import SessionLocal
from axile.server.core.log_config import execution_log_context
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import Account
from axile.server.repositories import get_latest_portfolio_id_by_account_id


async def create_job(
    sched: Scheduler,
    account: Account,
    triggers: list[CronTrigger],
    logger: "loguru.Logger | None" = None,
) -> None:
    """
    为账户创建定时执行任务.

    Parameters
    ----------
    sched : Scheduler
        当前服务使用的调度器实例。
    account : Account
        需要创建定时任务的账户。
    triggers : list[CronTrigger]
        账户配置对应的 Cron 触发器列表。
    logger : loguru.Logger | None, optional
        用于输出日志的 logger；未提供时使用全局 logger。

    Returns
    -------
    None
        该函数仅创建调度任务，不返回结果。
    """
    if logger is None:
        logger = loguru.logger

    acc_logger = logger.bind(
        **execution_log_context(
            account_id=account.id,
            account_name=account.name,
            channel=account.trade_channel,
        )
    )

    if not account.is_started:
        acc_logger.info("跳过定时任务创建 原因: 账户未启动")
        return

    async with SessionLocal() as session:
        portfolio_id = await get_latest_portfolio_id_by_account_id(session, cast("int", account.id))
        if portfolio_id is None:
            acc_logger.info("跳过定时任务创建, 原因: 组合未绑定")
            return

    try:
        from axile.server.execution import rebalance as rebalance_execution

        trigger = OrTrigger(triggers)
        next_run_time = trigger.get_next_fire_time(None, datetime.now())  # type: ignore[no-untyped-call]
        sched.add_job(  # type: ignore[no-untyped-call]
            func=rebalance_execution.execute_trade,
            args=[account.id, None, "scheduler"],
            trigger=trigger,
            id=str(account.id),
            next_run_time=next_run_time,
            max_instances=1,
        )

        acc_logger.info(f"定时任务创建成功 CRON={triggers}")
    except Exception as e:
        acc_logger.error(
            f"账户定时任务初始化失败 | 错误原因={str(e)}",
            exc_info=True,
        )
        raise


def delete_job(
    sched: Scheduler,
    account_id: int,
    logger: "loguru.Logger | None" = None,
) -> None:
    """
    在账户存在调度任务时删除它.

    Parameters
    ----------
    sched : Scheduler
        当前服务使用的调度器实例。
    account_id : int
        目标账户 ID。
    logger : loguru.Logger | None, optional
        用于输出日志的 logger；未提供时使用全局 logger。

    Returns
    -------
    None
        该函数仅删除调度任务，不返回结果。
    """
    if logger is None:
        logger = loguru.logger

    job: Union[Job, None] = sched.get_job(str(account_id))  # type: ignore[no-untyped-call]
    if job is not None:
        job.remove()  # type: ignore[no-untyped-call]
        logger.bind(**execution_log_context(account_id=account_id)).info("定时任务删除成功")

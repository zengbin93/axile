"""账户执行任务的调度辅助函数."""

from datetime import datetime
from typing import Union, cast

import loguru
from apscheduler.job import Job  # type: ignore[import-not-found]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]

from axile.server.core.db import SessionLocal
from axile.server.core.log_config import execution_log_context
from axile.server.core.scheduler import Scheduler
from axile.server.cron import SCHEDULER_TIMEZONE, combine_cron_triggers, is_blank_cron_expr
from axile.server.db.models import Account, ScheduleSkip
from axile.server.repositories import get_latest_portfolio_id_by_account_id
from axile.server.trading_calendar import (
    CalendarDecisionStatus,
    CalendarUnavailableReason,
    evaluate_channel_calendar_moment,
)


async def execute_scheduled_rebalance(account_id: int) -> None:
    """在进入执行链路前按北京时间和渠道日历判断 Cron 触发。"""
    triggered_at = datetime.now(SCHEDULER_TIMEZONE)
    async with SessionLocal() as session:
        account = await session.get(Account, account_id)
        if account is None or not account.is_started or is_blank_cron_expr(account.cron_expr):
            return
        channel = account.trade_channel

    try:
        decision = evaluate_channel_calendar_moment(channel, triggered_at)
    except Exception:  # noqa: BLE001 - 调度层日历故障沿用旧版 fail-open
        loguru.logger.bind(account_id=account_id, channel=str(channel)).exception("交易日历判断失败，按排程执行")
        decision = None

    context = {
        "account_id": account_id,
        "channel": str(channel),
        "calendar_id": decision.calendar_id if decision else None,
        "calendar_day": (decision.day if decision else triggered_at.date()).isoformat(),
    }
    account_logger = loguru.logger.bind(**context)
    if decision is not None and decision.status is CalendarDecisionStatus.AVAILABLE_CLOSED:
        try:
            async with SessionLocal() as session:
                session.add(
                    ScheduleSkip(
                        account_id=account_id,
                        channel=str(channel),
                        triggered_at=triggered_at.isoformat(),
                        calendar_id=decision.calendar_id or "",
                        calendar_day=decision.day,
                        calendar_label=decision.label or "",
                        reason_code=decision.reason_code or "CALENDAR.CLOSED",
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - 审计写入失败不能改变休市决策
            account_logger.exception("休市跳过记录写入失败")
        account_logger.info("排程因明确休市跳过")
        return

    if decision is not None and decision.status is CalendarDecisionStatus.UNAVAILABLE:
        reason = decision.unavailable_reason or CalendarUnavailableReason.READ_FAILED
        account_logger.bind(
            unavailable_reason=reason.value,
            action="execute_without_calendar",
        ).warning("交易日历不可用，按排程执行")

    from axile.domain.execution import ExecutionKind
    from axile.server.execution.intents import submit_intent

    result = await submit_intent(
        account_id,
        ExecutionKind.REBALANCE,
        "scheduler",
        on_conflict="skip",
    )
    if result.outcome == "skipped_busy":
        try:
            async with SessionLocal() as session:
                session.add(
                    ScheduleSkip(
                        account_id=account_id,
                        channel=str(channel),
                        triggered_at=triggered_at.isoformat(),
                        calendar_id=decision.calendar_id if decision is not None else "",
                        calendar_day=(decision.day if decision else triggered_at.date()),
                        calendar_label=decision.label if decision is not None and decision.label else "",
                        reason_code="BUSY",
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - 审计写入失败不能改变 busy 决策
            account_logger.exception("BUSY 跳过记录写入失败")
        account_logger.info("排程因已有执行在途跳过")
        return


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
        trigger = combine_cron_triggers(triggers)
        next_run_time = trigger.get_next_fire_time(None, datetime.now(SCHEDULER_TIMEZONE))  # type: ignore[no-untyped-call]
        sched.add_job(  # type: ignore[no-untyped-call]
            func=execute_scheduled_rebalance,
            args=[account.id],
            trigger=trigger,
            id=str(account.id),
            name=f"{account.name}#{account.id}",
            next_run_time=next_run_time,
            max_instances=1,
        )

        acc_logger.info(f"定时任务创建成功 CRON={account.cron_expr}")
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

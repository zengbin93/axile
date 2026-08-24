"""国内常驻账户通道的启动与交易日前准备."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Literal

from loguru import logger
from sqlmodel import col, select

from axile.common.trade_channel import TradeChannel
from axile.executor.china_futures_session import is_regular_night_session_transition
from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import Account
from axile.server.execution.worker_backend.manager import get_worker_backend_manager
from axile.server.trading_calendar import list_calendar_entries

CHINA_NIGHT_PREPARE_JOB_ID = "china-night-session-prepare"
CHINA_DAY_PREPARE_JOB_ID = "china-day-session-prepare"
_MAX_PREPARE_CONCURRENCY = 4


async def _expected_trading_day(mode: Literal["startup", "day", "night"], current: date) -> tuple[bool, str | None]:
    if mode == "startup":
        return True, None
    async with SessionLocal() as session:
        if mode == "day":
            rows = await list_calendar_entries(session, calendar_id="china", start=current, end=current)
            if not rows:
                logger.warning("缺少 china {} 交易日历，继续执行日盘通道准备", current)
                return True, None
            return rows[0].is_open, current.strftime("%Y%m%d") if rows[0].is_open else None

        current_rows = await list_calendar_entries(
            session,
            calendar_id="china",
            start=current,
            end=current,
        )
        if current_rows and not current_rows[0].is_open:
            return False, None
        rows = await list_calendar_entries(
            session,
            calendar_id="china",
            start=current + timedelta(days=1),
            end=current + timedelta(days=10),
            only_open=True,
        )
    if not rows:
        logger.warning("缺少 china {} 之后的交易日历，继续执行夜盘通道准备", current)
        return True, None
    target = rows[0]
    if not is_regular_night_session_transition(current, target.cal_date):
        logger.info(
            "跳过国内夜盘通道准备：{} 至下一交易日 {} 之间为休市窗口",
            current,
            target.cal_date,
        )
        return False, None
    return True, target.cal_date.strftime("%Y%m%d")


async def _started_china_channel_accounts() -> list[Account]:
    """返回已启用的 CTP 与天勤常驻账户."""
    async with SessionLocal() as session:
        statement = select(Account).where(
            col(Account.is_started).is_(True),
            col(Account.trade_channel).in_([TradeChannel.CTP, TradeChannel.TQ]),
        )
        return list((await session.execute(statement)).scalars().all())


async def _prepare_accounts(
    accounts: list[Account],
    mode: Literal["startup", "day", "night"],
    expected: str | None,
) -> None:
    """并发准备账户；天勤在日夜盘窗口先强制重建 worker."""
    semaphore = asyncio.Semaphore(_MAX_PREPARE_CONCURRENCY)
    manager = get_worker_backend_manager()

    async def prepare(account: Account) -> None:
        async with semaphore:
            try:
                if account.trade_channel == TradeChannel.TQ and mode != "startup" and account.id is not None:
                    await manager.drop_account(int(account.id))
                result = await manager.prepare_account(account, expected)
                logger.info(
                    "{} 通道准备完成 account_id={} mode={} trading_day={}",
                    account.trade_channel,
                    account.id,
                    mode,
                    result.get("trading_day", ""),
                )
            except Exception as exc:  # noqa: BLE001 - 单账户失败不得阻断其他账户
                logger.error("{} 通道准备失败 account_id={} mode={}: {}", account.trade_channel, account.id, mode, exc)

    await asyncio.gather(*(prepare(account) for account in accounts))


async def prepare_china_channel_accounts(
    mode: Literal["startup", "day", "night"],
    *,
    current: date | None = None,
) -> None:
    """准备全部已启用的国内常驻执行渠道."""
    should_prepare, expected = await _expected_trading_day(mode, current or date.today())
    if not should_prepare:
        logger.info("跳过国内 {} 通道准备：非对应交易窗口", mode)
        return
    await _prepare_accounts(await _started_china_channel_accounts(), mode, expected)


async def reconcile_china_channel_account(account: Account, *, reset: bool = False) -> None:
    """对齐 CTP 或天勤账户的常驻 worker."""
    if account.id is None:
        return
    manager = get_worker_backend_manager()
    if reset:
        await manager.drop_account(int(account.id))
    if account.trade_channel not in {TradeChannel.CTP, TradeChannel.TQ} or not account.is_started:
        return
    try:
        await manager.prepare_account(account)
    except Exception as exc:  # noqa: BLE001 - 落库成功不应因外部渠道失败而回滚
        logger.error("{} 账户通道准备失败 account_id={}: {}", account.trade_channel, account.id, exc)


async def drop_account_worker(account_id: int) -> None:
    """关闭账户可能持有的常驻 Worker。"""
    await get_worker_backend_manager().drop_account(account_id)


def register_china_channel_jobs(scheduler: Scheduler) -> None:
    """注册国内常驻渠道的夜盘前与日盘前准备任务."""
    common = {
        "trigger": "cron",
        "replace_existing": True,
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 1800,
    }
    _ = scheduler.add_job(
        prepare_china_channel_accounts,
        hour=20,
        minute=30,
        id=CHINA_NIGHT_PREPARE_JOB_ID,
        args=["night"],
        **common,
    )
    _ = scheduler.add_job(
        prepare_china_channel_accounts,
        hour=8,
        minute=30,
        id=CHINA_DAY_PREPARE_JOB_ID,
        args=["day"],
        **common,
    )


__all__ = [
    "drop_account_worker",
    "prepare_china_channel_accounts",
    "reconcile_china_channel_account",
    "register_china_channel_jobs",
]

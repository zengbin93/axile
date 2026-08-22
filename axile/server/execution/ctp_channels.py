"""CTP 常驻账户通道的启动与交易日前准备。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Literal

from loguru import logger
from sqlmodel import col, select

from axile.common.trade_channel import TradeChannel
from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import Account
from axile.server.execution.worker_backend.manager import get_worker_backend_manager
from axile.server.trading_calendar import list_calendar_entries

CTP_NIGHT_PREPARE_JOB_ID = "ctp-night-session-prepare"
CTP_DAY_PREPARE_JOB_ID = "ctp-day-session-prepare"
_MAX_PREPARE_CONCURRENCY = 4


async def _expected_trading_day(mode: Literal["startup", "day", "night"], current: date) -> tuple[bool, str | None]:
    if mode == "startup":
        return True, None
    async with SessionLocal() as session:
        if mode == "day":
            rows = await list_calendar_entries(session, exchange="CFFEX", start=current, end=current)
            if not rows:
                logger.warning("缺少 CFFEX {} 交易日历，继续执行日盘通道准备", current)
                return True, None
            return rows[0].is_open, current.strftime("%Y%m%d") if rows[0].is_open else None

        rows = await list_calendar_entries(
            session,
            exchange="CFFEX",
            start=current + timedelta(days=1),
            end=current + timedelta(days=10),
            only_open=True,
        )
    if not rows:
        logger.warning("缺少 CFFEX {} 之后的交易日历，继续执行夜盘通道准备", current)
        return True, None
    target = next((row for row in rows if row.pretrade_date == current), None)
    return (target is not None, target.cal_date.strftime("%Y%m%d") if target else None)


async def _started_ctp_accounts() -> list[Account]:
    async with SessionLocal() as session:
        statement = select(Account).where(
            col(Account.is_started).is_(True),
            col(Account.trade_channel) == TradeChannel.CTP,
        )
        return list((await session.execute(statement)).scalars().all())


async def prepare_ctp_accounts(
    mode: Literal["startup", "day", "night"],
    *,
    current: date | None = None,
) -> None:
    """按启动或交易日前窗口准备所有已启用 CTP 账户。"""
    should_prepare, expected = await _expected_trading_day(mode, current or date.today())
    if not should_prepare:
        logger.info("跳过 CTP {} 通道准备：非对应交易窗口", mode)
        return
    accounts = await _started_ctp_accounts()
    semaphore = asyncio.Semaphore(_MAX_PREPARE_CONCURRENCY)
    manager = get_worker_backend_manager()

    async def prepare(account: Account) -> None:
        async with semaphore:
            try:
                result = await manager.prepare_account(account, expected)
                logger.info(
                    "CTP 通道准备完成 account_id={} mode={} trading_day={}",
                    account.id,
                    mode,
                    result.get("trading_day", ""),
                )
            except Exception as exc:  # noqa: BLE001 - 单账户失败不得阻断其他账户
                logger.error("CTP 通道准备失败 account_id={} mode={}: {}", account.id, mode, exc)

    await asyncio.gather(*(prepare(account) for account in accounts))


async def reconcile_ctp_account(account: Account, *, reset: bool = False) -> None:
    """对齐单个账户的 CTP Worker，失败仅记录而不回滚账户变更。"""
    if account.id is None:
        return
    manager = get_worker_backend_manager()
    if reset:
        await manager.drop_account(int(account.id))
    if account.trade_channel != TradeChannel.CTP or not account.is_started:
        return
    try:
        await manager.prepare_account(account)
    except Exception as exc:  # noqa: BLE001 - 账户配置已落库，通道可由后续准备恢复
        logger.error("CTP 账户通道准备失败 account_id={}: {}", account.id, exc)


async def drop_account_worker(account_id: int) -> None:
    """关闭账户可能持有的常驻 Worker。"""
    await get_worker_backend_manager().drop_account(account_id)


def register_ctp_channel_jobs(scheduler: Scheduler) -> None:
    """注册夜盘前与日盘前的 CTP 通道准备任务。"""
    common = {
        "trigger": "cron",
        "replace_existing": True,
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 1800,
    }
    _ = scheduler.add_job(
        prepare_ctp_accounts,
        hour=20,
        minute=30,
        id=CTP_NIGHT_PREPARE_JOB_ID,
        args=["night"],
        **common,
    )
    _ = scheduler.add_job(
        prepare_ctp_accounts,
        hour=8,
        minute=30,
        id=CTP_DAY_PREPARE_JOB_ID,
        args=["day"],
        **common,
    )


__all__ = [
    "drop_account_worker",
    "prepare_ctp_accounts",
    "reconcile_ctp_account",
    "register_ctp_channel_jobs",
]

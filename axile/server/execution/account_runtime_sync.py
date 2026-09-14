"""账户数据库真源与 scheduler / worker 运行态之间的可恢复对齐。"""

from __future__ import annotations

from typing import Any, cast

from loguru import logger
from sqlmodel import select

from axile.server.api.routes.account_support import _reconcile_account_job
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import Account
from axile.server.db.models.account_runtime_sync import AccountRuntimeSync, AccountRuntimeSyncAttempt
from axile.server.db.models.base import now_str
from axile.server.execution.ctp_channels import reconcile_china_channel_account


async def enqueue_account_runtime_sync(
    session: Any,
    account_id: int,
    *,
    reset_worker: bool,
    create_request_key: str | None = None,
) -> AccountRuntimeSync:
    """在账户写事务内登记最新运行态目标。"""
    sync = await session.scalar(select(AccountRuntimeSync).where(AccountRuntimeSync.account_id == account_id))
    if sync is None:
        sync = AccountRuntimeSync(
            account_id=account_id,
            reset_worker=reset_worker,
            create_request_key=create_request_key,
        )
        session.add(sync)
        return sync
    sync.revision += 1
    sync.status = "pending"
    sync.reset_worker = sync.reset_worker or reset_worker
    sync.last_error = None
    sync.requested_at = now_str()
    sync.synchronized_at = None
    session.add(sync)
    return sync


async def reconcile_account_runtime(session: Any, sched: Scheduler, account: Account) -> AccountRuntimeSync:
    """执行一次幂等对齐，并持久化结果；异常不会否定已提交的账户配置。"""
    account_id = cast("int", account.id)
    sync = await session.scalar(select(AccountRuntimeSync).where(AccountRuntimeSync.account_id == account_id))
    if sync is None:
        sync = AccountRuntimeSync(account_id=account_id)
        session.add(sync)
        await session.commit()

    revision = sync.revision
    sync.attempts += 1
    sync.last_attempt_at = now_str()
    session.add(sync)
    # 尝试记账必须先提交：`sync` 已是脏对象，一旦 `_reconcile_account_job` 里的
    # 查询触发 autoflush，UPDATE 会开启写事务并横跨下面的跨进程等待。worker
    # 在 prepare 收尾写账户控制计数增量时拿不到写锁，报 ``database is locked``，
    # 整个账户对齐失败。WAL 也救不了这种"写事务横跨 await"的场景。
    await session.commit()
    try:
        await _reconcile_account_job(session, sched, account)
        await reconcile_china_channel_account(account, reset=sync.reset_worker)
    except Exception as exc:  # noqa: BLE001 - 外部进程态故障必须转为可恢复状态
        message = str(exc)
        sync.status = "failed"
        sync.last_error = message
        session.add(AccountRuntimeSyncAttempt(account_id=account_id, revision=revision, succeeded=False, error=message))
        session.add(sync)
        await session.commit()
        logger.exception("账户运行态对齐失败 account_id={} revision={}", account_id, revision)
        return sync

    await session.refresh(sync)
    if sync.revision == revision:
        sync.status = "synchronized"
        sync.last_error = None
        sync.reset_worker = False
        sync.synchronized_at = now_str()
    session.add(AccountRuntimeSyncAttempt(account_id=account_id, revision=revision, succeeded=True))
    session.add(sync)
    await session.commit()
    return sync


async def recover_account_runtime_on_startup(session: Any, sched: Scheduler) -> None:
    """重启时从数据库真源重建所有账户的进程运行态。"""
    accounts = list((await session.execute(select(Account))).scalars().all())
    for account in accounts:
        try:
            # scheduler 与 worker 都是进程态；即使上一次进程已记录 synchronized，
            # 重启后也必须按数据库中的目标重新收敛。
            await reconcile_account_runtime(session, sched, account)
        except Exception:  # noqa: BLE001 - 单账户故障不阻断服务启动和其他账户恢复
            logger.exception("启动恢复账户运行态失败 account_id={}", account.id)

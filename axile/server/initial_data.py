"""从已持久化账户恢复调度任务的启动辅助函数."""

from sqlmodel import select

from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import scheduler
from axile.server.cron import is_blank_cron_expr, parse_cron_expr
from axile.server.db.models import Account
from axile.server.execution.scheduler import create_job


async def init_scheduler() -> None:
    """在服务启动期间为已持久化账户重建调度任务."""
    async with SessionLocal() as session:
        """启动时，将所有账户创建定时任务"""
        accounts = (await session.execute(select(Account))).scalars().all()

        for account in accounts:
            # 空 cron = 仅手动，无调度任务；与更新路径 reconcile 口径一致。
            if is_blank_cron_expr(account.cron_expr):
                continue
            cron_expr = parse_cron_expr(account.cron_expr)

            await create_job(scheduler, account, cron_expr)  # type: ignore[misc]

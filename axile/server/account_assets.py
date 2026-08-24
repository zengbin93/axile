"""账户资产主动查询服务."""

from __future__ import annotations

import asyncio

from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.server.db.models import Account
from axile.server.execution.dispatch import ExecutionBackendKind, resolve_execution_backend_kind
from axile.server.execution.factory import create_executor_instance
from axile.server.execution.worker_backend.manager import (
    WorkerBackendTimeoutError,
    get_worker_backend_manager,
)

_ACCOUNT_ASSET_TIMEOUT_SECONDS = 30.0


def _query_inline_account_assets(account: Account) -> UnifiedAccountAssets:
    """在线程内创建执行器、查询资产并释放渠道资源."""
    executor = create_executor_instance(account)
    try:
        return executor.get_account_assets()
    finally:
        stop = getattr(executor, "stop", None)
        close = getattr(executor, "close", None)
        if callable(stop):
            stop()
        elif callable(close):
            close()


async def query_account_assets(account: Account) -> UnifiedAccountAssets:
    """按渠道执行后端策略查询最新账户资产."""
    if resolve_execution_backend_kind(account.trade_channel) == ExecutionBackendKind.PROCESS:
        try:
            return await get_worker_backend_manager().get_account_assets(account)
        except WorkerBackendTimeoutError as exc:
            raise TimeoutError("账户资产查询超时") from exc
    return await asyncio.wait_for(
        asyncio.to_thread(_query_inline_account_assets, account),
        timeout=_ACCOUNT_ASSET_TIMEOUT_SECONDS,
    )

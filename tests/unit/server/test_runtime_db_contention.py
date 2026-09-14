"""SQLite 多进程写竞争的回归测试.

覆盖两类 ``database is locked`` 场景：
1. 引擎并发 PRAGMA（WAL + busy_timeout）确实逐连接生效；
2. ``reconcile_account_runtime`` 不得把写事务横跨跨进程 prepare 等待，
   否则 worker 收尾写账户控制计数增量时拿不到写锁。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

# 导入模型包以将全部数据表登记到 ``SQLModel.metadata``
import axile.server.db.models  # noqa: F401
from axile.server.core.db import SQLITE_BUSY_TIMEOUT_MS, register_sqlite_concurrency_pragmas
from axile.server.db.models import Account, AccountRuntimeSync
from axile.server.execution import account_runtime_sync


def _file_engine(db_path: Path, *, busy_timeout_ms: int) -> AsyncEngine:
    """在指定路径上建一个文件型 aiosqlite 引擎并设置给定忙等待上限."""
    target = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    @event.listens_for(target.sync_engine, "connect")
    def _set_busy_timeout(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        finally:
            cursor.close()

    return target


def test_engine_connections_enable_wal_and_busy_timeout(tmp_path: Path) -> None:
    asyncio.run(_assert_pragmas(tmp_path))


async def _assert_pragmas(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path / "pragma.db", busy_timeout_ms=SQLITE_BUSY_TIMEOUT_MS)
    register_sqlite_concurrency_pragmas(engine)
    try:
        async with engine.connect() as conn:
            journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
            busy_timeout = int((await conn.execute(text("PRAGMA busy_timeout"))).scalar_one())
            synchronous = int((await conn.execute(text("PRAGMA synchronous"))).scalar_one())
    finally:
        await engine.dispose()

    assert journal_mode == "wal"
    assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS
    # PRAGMA synchronous: 1 == NORMAL
    assert synchronous == 1


def test_reconcile_account_runtime_does_not_hold_write_lock_across_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_reconcile_scenario(tmp_path, monkeypatch))


async def _reconcile_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server_engine = _file_engine(tmp_path / "runtime.db", busy_timeout_ms=SQLITE_BUSY_TIMEOUT_MS)
    # 模拟 worker 进程的连接：同样写库，但忙等待上限只有 500ms，
    # 旧代码里它会在 prepare 收尾撞锁并抛 ``database is locked``。
    contender_engine = _file_engine(tmp_path / "runtime.db", busy_timeout_ms=500)
    try:
        async with server_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        session_factory = async_sessionmaker(server_engine, expire_on_commit=False)
        account = Account(id=3)
        probe: dict[str, bool] = {}

        async def _fake_reconcile_job(session: Any, sched: Any, account: Any) -> None:
            # 还原真实路径：首个查询会触发 autoflush，旧代码正是在这里
            # 把脏的 sync 对象刷成 UPDATE，留下横跨 prepare 的写事务。
            await session.scalar(select(AccountRuntimeSync).where(AccountRuntimeSync.account_id == account.id))

        async def _fake_prepare(account: Any, *, reset: bool = False) -> None:
            # SQLModel 默认表名是类名小写，从模型取，避免手写错。
            sync_table = AccountRuntimeSync.__table__.name
            async with contender_engine.begin() as conn:
                await conn.execute(text(f"UPDATE {sync_table} SET last_error = 'probe'"))
            probe["written"] = True

        monkeypatch.setattr(account_runtime_sync, "_reconcile_account_job", _fake_reconcile_job)
        monkeypatch.setattr(account_runtime_sync, "reconcile_china_channel_account", _fake_prepare)

        async with session_factory() as session:
            sync = await account_runtime_sync.reconcile_account_runtime(session, None, account)

        assert probe.get("written") is True
        assert sync.status == "synchronized"
    finally:
        await server_engine.dispose()
        await contender_engine.dispose()

"""账户运行态 reconcile 的提交后故障与恢复测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from axile.server.db.models.account_runtime_sync import AccountRuntimeSync, AccountRuntimeSyncAttempt
from axile.server.execution import account_runtime_sync


class _Session:
    """只实现 reconcile 测试需要的异步会话表面。"""

    def __init__(self, sync: AccountRuntimeSync) -> None:
        self.sync = sync
        self.added: list[object] = []
        self.commits = 0

    async def scalar(self, _statement: object) -> AccountRuntimeSync:
        return self.sync

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _value: object) -> None:
        return None


class _StartupSession:
    """只实现启动恢复测试需要的查询表面。"""

    def __init__(self, accounts: list[object]) -> None:
        self.accounts = accounts

    async def execute(self, _statement: object) -> object:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.accounts))


def test_post_commit_runtime_failure_is_recorded_and_retry_converges(monkeypatch: pytest.MonkeyPatch) -> None:
    """运行态失败不回滚账户真源，显式重试可收敛且留下两条审计。"""
    sync = AccountRuntimeSync(account_id=7)
    session = _Session(sync)
    account = SimpleNamespace(id=7)

    async def fail_scheduler(*_args: object) -> None:
        raise RuntimeError("scheduler unavailable")

    async def unused_worker(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("scheduler 失败时不应继续准备 worker")

    monkeypatch.setattr(account_runtime_sync, "_reconcile_account_job", fail_scheduler)
    monkeypatch.setattr(account_runtime_sync, "reconcile_china_channel_account", unused_worker)
    failed = asyncio.run(account_runtime_sync.reconcile_account_runtime(session, SimpleNamespace(), account))

    assert failed.status == "failed"
    assert failed.last_error == "scheduler unavailable"
    assert failed.attempts == 1
    assert isinstance(session.added[-2], AccountRuntimeSyncAttempt)
    assert session.added[-2].succeeded is False

    async def succeed(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(account_runtime_sync, "_reconcile_account_job", succeed)
    monkeypatch.setattr(account_runtime_sync, "reconcile_china_channel_account", succeed)
    recovered = asyncio.run(account_runtime_sync.reconcile_account_runtime(session, SimpleNamespace(), account))

    assert recovered.status == "synchronized"
    assert recovered.attempts == 2
    attempts = [item for item in session.added if isinstance(item, AccountRuntimeSyncAttempt)]
    assert [attempt.succeeded for attempt in attempts] == [False, True]


def test_startup_reconciles_even_previously_synchronized_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """进程重启会丢失内存 scheduler/worker，不能被旧成功记录短路。"""
    account = SimpleNamespace(id=7)
    calls: list[object] = []

    async def reconcile(session: object, sched: object, current: object) -> None:
        calls.append((session, sched, current))

    monkeypatch.setattr(account_runtime_sync, "reconcile_account_runtime", reconcile)
    session = _StartupSession([account])
    scheduler = SimpleNamespace()

    asyncio.run(account_runtime_sync.recover_account_runtime_on_startup(session, scheduler))

    assert calls == [(session, scheduler, account)]

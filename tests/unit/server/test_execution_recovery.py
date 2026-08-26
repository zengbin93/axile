"""启动恢复：QUEUED 可续，RUNNING 中断。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import ExecutionKind, ExecutionTaskStatus
from axile.server.db.models import Account
from axile.server.db.models.execution_intent import ExecutionIntent
from axile.server.execution import dispatcher as dispatcher_module
from axile.server.execution import intents as intents_module
from axile.server.execution import records as records_module
from axile.server.execution.dispatcher import recover_intents_on_startup
from axile.server.execution.intents import PROCESS_INTERRUPTED_REASON, get_intent
from axile.server.execution.registry import get_queued_execution_id


def _account() -> Account:
    return Account(
        id=3,
        name="recovery-test",
        market="期货",
        trade_channel=TradeChannel.CTP,
        account_control_preset="default",
        account_config={"api_key": "k", "secret_key": "s", "is_testnet": True},
        is_started=True,
        cron_expr="*/15 * * * *",
        remark=None,
        brokerage="ctp",
        weight_precision=0.001,
        long_leverage=1.0,
        short_leverage=1.0,
        algorithm={"method": "SINGLE-MAKER"},
        empty_positions_algorithm=None,
        trade_rules={},
        forbidden_symbols=[],
        risk_symbols=[],
        feishu_key=None,
        write_empty_record=0,
    )


@asynccontextmanager
async def _db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(intents_module, "SessionLocal", factory)
        monkeypatch.setattr(records_module, "SessionLocal", factory)
        monkeypatch.setattr(dispatcher_module, "SessionLocal", factory)
        monkeypatch.setattr(dispatcher_module, "wake_account_dispatcher", lambda _id: None)

        async def fake_append(*_a: object, **_k: object) -> object:
            return None

        monkeypatch.setattr(records_module, "append_error_execute_record", fake_append)
        async with factory() as session:
            session.add(_account())
            await session.commit()
        yield factory
    finally:
        await engine.dispose()


def test_recover_interrupts_running_and_restores_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> tuple[str | None, str | None]:
        async with _db(monkeypatch) as factory:
            async with factory() as session:
                session.add(
                    ExecutionIntent(
                        execution_id="run-1",
                        account_id=3,
                        kind=ExecutionKind.REBALANCE,
                        trigger_source="manual",
                        status=ExecutionTaskStatus.RUNNING,
                        payload={},
                    )
                )
                session.add(
                    ExecutionIntent(
                        execution_id="queue-1",
                        account_id=3,
                        kind=ExecutionKind.REBALANCE,
                        trigger_source="scheduler",
                        status=ExecutionTaskStatus.QUEUED,
                        payload={},
                    )
                )
                await session.commit()
            await recover_intents_on_startup()
            running = await get_intent("run-1")
            queued = await get_intent("queue-1")
            return (
                None if running is None else running.status.value,
                None if queued is None else queued.status.value,
            )

    running_status, queued_status = asyncio.run(_run())
    assert running_status == ExecutionTaskStatus.FAILED.value
    assert queued_status == ExecutionTaskStatus.QUEUED.value
    assert get_queued_execution_id(3) == "queue-1"
    _ = PROCESS_INTERRUPTED_REASON

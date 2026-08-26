"""执行意图准入冲突表与 CAS。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import ExecutionKind, ExecutionTaskStatus
from axile.server.db.models import Account
from axile.server.execution import intents as intents_module
from axile.server.execution.intents import (
    IntentSnapshot,
    SubmitResult,
    cas_intent_status,
    get_intent,
    submit_intent,
)
from axile.server.execution.live import live_hub
from axile.server.execution.registry import (
    AccountExecutionAlreadyRunningError,
    clear_queued_execution,
    clear_running_execution,
    get_queued_execution_id,
    try_register_running_execution,
)


def _account(*, account_id: int = 1) -> Account:
    return Account(
        id=account_id,
        name="intent-test",
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
async def _intent_db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(intents_module, "SessionLocal", factory)
        monkeypatch.setattr(intents_module, "_wake", lambda _account_id: None)
        async with factory() as session:
            session.add(_account())
            await session.commit()
        yield factory
    finally:
        await engine.dispose()
        clear_queued_execution(1, get_queued_execution_id(1) or "")
        clear_running_execution(1, "x")


def test_submit_intent_creates_queued_rebalance(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> tuple[SubmitResult, str | None]:
        async with _intent_db(monkeypatch):
            result = await submit_intent(1, ExecutionKind.REBALANCE, "manual")
            return result, get_queued_execution_id(1)

    result, queued_id = asyncio.run(_run())
    assert result.outcome == "created"
    assert result.execution_id
    assert queued_id == result.execution_id


def test_submit_intent_coalesces_queued_rebalance(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> tuple[SubmitResult, SubmitResult]:
        async with _intent_db(monkeypatch):
            first = await submit_intent(1, ExecutionKind.REBALANCE, "manual")
            second = await submit_intent(1, ExecutionKind.REBALANCE, "scheduler")
            return first, second

    first, second = asyncio.run(_run())
    assert first.outcome == "created"
    assert second.outcome == "coalesced"
    assert second.execution_id == first.execution_id


def test_submit_intent_recovers_from_concurrent_initial_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    original_insert = intents_module._insert_intent
    first_call = True

    async def competing_insert(
        *,
        account: Account,
        kind: ExecutionKind,
        trigger_source: str,
        payload: dict[str, object],
    ) -> IntentSnapshot:
        nonlocal first_call
        if first_call:
            first_call = False
            await original_insert(
                account=account,
                kind=kind,
                trigger_source=trigger_source,
                payload=payload,
            )
            raise IntegrityError("concurrent queued intent", {}, RuntimeError("unique constraint"))
        return await original_insert(
            account=account,
            kind=kind,
            trigger_source=trigger_source,
            payload=payload,
        )

    async def _run() -> SubmitResult:
        async with _intent_db(monkeypatch):
            monkeypatch.setattr(intents_module, "_insert_intent", competing_insert)
            return await submit_intent(1, ExecutionKind.REBALANCE, "manual")

    result = asyncio.run(_run())
    assert result.outcome == "coalesced"
    assert result.execution_id is not None


def test_cas_intent_status_rejects_stale_expected_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> tuple[bool, bool, ExecutionTaskStatus | None]:
        async with _intent_db(monkeypatch):
            submitted = await submit_intent(1, ExecutionKind.REBALANCE, "manual")
            assert submitted.execution_id is not None
            terminated = await cas_intent_status(
                submitted.execution_id,
                ExecutionTaskStatus.QUEUED,
                ExecutionTaskStatus.TERMINATED,
            )
            stale_promotion = await cas_intent_status(
                submitted.execution_id,
                ExecutionTaskStatus.QUEUED,
                ExecutionTaskStatus.RUNNING,
            )
            intent = await get_intent(submitted.execution_id)
            return terminated, stale_promotion, None if intent is None else intent.status

    terminated, stale_promotion, status = asyncio.run(_run())
    assert terminated is True
    assert stale_promotion is False
    assert status == ExecutionTaskStatus.TERMINATED


def test_submit_intent_clear_replaces_queued_rebalance(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_finalize(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(
        "axile.server.execution.registry._finalize_terminated_queued_execution",
        fake_finalize,
    )

    async def _run() -> tuple[str, SubmitResult, str | None]:
        async with _intent_db(monkeypatch):
            first = await submit_intent(1, ExecutionKind.REBALANCE, "manual")
            assert first.execution_id is not None
            replaced = await submit_intent(1, ExecutionKind.CLEAR_POSITIONS, "empty_positions")
            return first.execution_id, replaced, get_queued_execution_id(1)

    old_id, replaced, queued_id = asyncio.run(_run())
    assert replaced.outcome == "created"
    assert replaced.execution_id != old_id
    assert queued_id == replaced.execution_id


def test_submit_intent_clear_conflicts_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        try_register_running_execution(1, "exec-running")

        async def _run() -> None:
            async with _intent_db(monkeypatch):
                await submit_intent(1, ExecutionKind.CLEAR_POSITIONS, "empty_positions")

        with pytest.raises(AccountExecutionAlreadyRunningError):
            asyncio.run(_run())
    finally:
        clear_running_execution(1, "exec-running")


def test_submit_intent_rebalance_queues_behind_running(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        try_register_running_execution(1, "exec-running")

        async def _run() -> tuple[SubmitResult, str | None]:
            async with _intent_db(monkeypatch):
                result = await submit_intent(1, ExecutionKind.REBALANCE, "manual")
                return result, get_queued_execution_id(1)

        result, queued_id = asyncio.run(_run())
        assert result.outcome == "created"
        assert queued_id == result.execution_id
    finally:
        clear_running_execution(1, "exec-running")
        queued_id = get_queued_execution_id(1)
        if queued_id is not None:
            clear_queued_execution(1, queued_id)


def test_cron_busy_returns_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        try_register_running_execution(1, "exec-running")
        from axile.server.execution.registry import set_queued_execution

        set_queued_execution(1, "exec-queued")

        async def _run() -> SubmitResult:
            async with _intent_db(monkeypatch):
                return await submit_intent(
                    1,
                    ExecutionKind.REBALANCE,
                    "scheduler",
                    on_conflict="skip",
                )

        result = asyncio.run(_run())
        assert result.outcome == "skipped_busy"
        assert result.execution_id is None
    finally:
        clear_running_execution(1, "exec-running")
        clear_queued_execution(1, "exec-queued")


def test_submit_intent_clear_conflicts_when_queued_rebalance_promoted(monkeypatch: pytest.MonkeyPatch) -> None:
    original_cas = intents_module.cas_intent_status

    async def promote_then_fail(
        execution_id: str,
        expected: ExecutionTaskStatus,
        target: ExecutionTaskStatus,
        **fields: object,
    ) -> bool:
        if target == ExecutionTaskStatus.TERMINATED:
            await original_cas(execution_id, ExecutionTaskStatus.QUEUED, ExecutionTaskStatus.RUNNING)
            return False
        return await original_cas(execution_id, expected, target, **fields)

    async def _run() -> tuple[ExecutionKind | None, ExecutionKind | None]:
        async with _intent_db(monkeypatch):
            first = await submit_intent(1, ExecutionKind.REBALANCE, "manual")
            assert first.execution_id is not None
            monkeypatch.setattr(intents_module, "cas_intent_status", promote_then_fail)
            with pytest.raises(AccountExecutionAlreadyRunningError):
                await submit_intent(1, ExecutionKind.CLEAR_POSITIONS, "empty_positions")
            running, queued = await intents_module.load_active_intents(1)
            return (
                None if running is None else running.kind,
                None if queued is None else queued.kind,
            )

    running_kind, queued_kind = asyncio.run(_run())
    assert running_kind == ExecutionKind.REBALANCE
    assert queued_kind is None


def test_sync_live_clears_hub_when_slots_empty() -> None:
    live_hub.publish_slots(
        account_id=91,
        execution_id="exec-stale-queued",
        kind="rebalance",
        status="queued",
        phase="queued",
        pending_execution_id=None,
        pending_kind=None,
    )
    assert live_hub.progress_for(91) is not None
    intents_module.sync_account_live(91)
    assert live_hub.progress_for(91) is None


def test_dashboard_ignores_terminal_progress_frames() -> None:
    from axile.domain.execution import ExecutionEventType

    live_hub.publish(
        execution_id="exec-done-92",
        account_id=92,
        event_type=ExecutionEventType.EXECUTION_COMPLETED,
        kind="rebalance",
    )
    progress = live_hub.progress_for(92)
    assert progress is not None
    assert progress["status"] == "done"
    live_hub.clear_live_account(92)
    assert live_hub.progress_for(92) is None

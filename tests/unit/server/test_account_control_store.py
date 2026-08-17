"""账户控制持久化 store 测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.models import (
    AccountControlBucketType,
    AccountControlCounterDeltaWrite,
    AccountControlDecision,
    AccountControlEventWrite,
    AccountControlScopeType,
)
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from axile.server.account_control.store import AccountControlStore
from axile.server.db.models import Account, AccountControlCounterDelta, AccountControlEvent


def _build_account() -> Account:
    return Account(
        name="ctp-testnet-sim",
        market="加密货币",
        trade_channel=TradeChannel.CTP,
        account_control_preset="default",
        account_control_override=None,
        account_config={"api_key": "key", "secret_key": "secret", "is_testnet": True},
        is_started=True,
        cron_expr="*/5 * * * *",
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
        portfolio_id=1,
        write_empty_record=0,
    )


def _build_store(session: AsyncSession) -> AccountControlStore:
    return AccountControlStore(session)


@asynccontextmanager
async def _session_scope() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def test_load_daily_counters_aggregates_account_and_symbol_scopes() -> None:
    """执行开始时应按账户日窗口聚合 append-only delta 作为基线。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account()
            session.add(account)
            await session.commit()
            assert account.id is not None

            session.add_all(
                [
                    AccountControlCounterDelta(
                        account_id=account.id,
                        execution_id="exec-a",
                        control_date="2026-03-22",
                        bucket_type=AccountControlBucketType.DAY,
                        bucket_start="2026-03-22T00:00:00",
                        scope_type=AccountControlScopeType.ACCOUNT,
                        symbol=None,
                        operation="place_order",
                        delta_count=2,
                        delta_uid="delta-day-account-a",
                    ),
                    AccountControlCounterDelta(
                        account_id=account.id,
                        execution_id="exec-b",
                        control_date="2026-03-22",
                        bucket_type=AccountControlBucketType.DAY,
                        bucket_start="2026-03-22T00:00:00",
                        scope_type=AccountControlScopeType.ACCOUNT,
                        symbol=None,
                        operation="place_order",
                        delta_count=3,
                        delta_uid="delta-day-account-b",
                    ),
                    AccountControlCounterDelta(
                        account_id=account.id,
                        execution_id="exec-c",
                        control_date="2026-03-22",
                        bucket_type=AccountControlBucketType.MINUTE,
                        bucket_start="2026-03-22T09:31:00",
                        scope_type=AccountControlScopeType.ACCOUNT,
                        symbol=None,
                        operation="query_order",
                        delta_count=4,
                        delta_uid="delta-minute-account-c",
                    ),
                    AccountControlCounterDelta(
                        account_id=account.id,
                        execution_id="exec-d",
                        control_date="2026-03-22",
                        bucket_type=AccountControlBucketType.DAY,
                        bucket_start="2026-03-22T00:00:00",
                        scope_type=AccountControlScopeType.SYMBOL,
                        symbol="BTCUSDT",
                        operation="place_order",
                        delta_count=5,
                        delta_uid="delta-day-symbol-d",
                    ),
                    AccountControlCounterDelta(
                        account_id=account.id,
                        execution_id="exec-e",
                        control_date="2026-03-21",
                        bucket_type=AccountControlBucketType.DAY,
                        bucket_start="2026-03-21T00:00:00",
                        scope_type=AccountControlScopeType.ACCOUNT,
                        symbol=None,
                        operation="place_order",
                        delta_count=99,
                        delta_uid="delta-other-date",
                    ),
                ]
            )
            await session.commit()

            snapshot = await _build_store(session).load_daily_counters(account.id, "2026-03-22")

            assert (
                snapshot.get_count(
                    bucket_type=AccountControlBucketType.DAY,
                    bucket_start="2026-03-22T00:00:00",
                    operation="place_order",
                )
                == 5
            )
            assert (
                snapshot.get_count(
                    bucket_type=AccountControlBucketType.MINUTE,
                    bucket_start="2026-03-22T09:31:00",
                    operation="query_order",
                )
                == 4
            )
            assert (
                snapshot.get_count(
                    bucket_type=AccountControlBucketType.DAY,
                    bucket_start="2026-03-22T00:00:00",
                    operation="place_order",
                    symbol="BTCUSDT",
                )
                == 5
            )
            assert (
                snapshot.get_count(
                    bucket_type=AccountControlBucketType.DAY,
                    bucket_start="2026-03-21T00:00:00",
                    operation="place_order",
                )
                == 0
            )

    asyncio.run(scenario())


def test_counter_snapshot_supports_arbitrary_string_operation_keys() -> None:
    """snapshot 应支持任意字符串 operation key。"""
    snapshot = AccountControlCounterSnapshot()

    snapshot.add(
        bucket_type=AccountControlBucketType.DAY,
        bucket_start="2026-03-22T00:00:00",
        operation="query_positions",
        delta_count=2,
    )
    snapshot.add(
        bucket_type=AccountControlBucketType.DAY,
        bucket_start="2026-03-22T00:00:00",
        operation="query_positions",
        delta_count=3,
        symbol="rb2505",
    )

    assert (
        snapshot.get_count(
            bucket_type=AccountControlBucketType.DAY,
            bucket_start="2026-03-22T00:00:00",
            operation="query_positions",
        )
        == 2
    )
    assert (
        snapshot.get_count(
            bucket_type=AccountControlBucketType.DAY,
            bucket_start="2026-03-22T00:00:00",
            operation="query_positions",
            symbol="rb2505",
        )
        == 3
    )


def test_flush_execution_records_persists_allowed_blocked_and_failed_facts() -> None:
    """执行结束时应批量插入 delta 和事件，blocked 仅写事件不消耗预算。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account()
            session.add(account)
            await session.commit()
            assert account.id is not None

            store = _build_store(session)
            await store.flush_execution_records(
                counter_deltas=[
                    AccountControlCounterDeltaWrite(
                        account_id=account.id,
                        execution_id="exec-1",
                        control_date="2026-03-22",
                        bucket_type=AccountControlBucketType.DAY,
                        bucket_start="2026-03-22T00:00:00",
                        scope_type=AccountControlScopeType.ACCOUNT,
                        symbol=None,
                        operation="place_order",
                        delta_count=1,
                        delta_uid="delta-allowed-day",
                    ),
                    AccountControlCounterDeltaWrite(
                        account_id=account.id,
                        execution_id="exec-1",
                        control_date="2026-03-22",
                        bucket_type=AccountControlBucketType.DAY,
                        bucket_start="2026-03-22T00:00:00",
                        scope_type=AccountControlScopeType.SYMBOL,
                        symbol="BTCUSDT",
                        operation="place_order",
                        delta_count=1,
                        delta_uid="delta-allowed-symbol",
                    ),
                ],
                events=[
                    AccountControlEventWrite(
                        account_id=account.id,
                        control_date="2026-03-22",
                        execution_id="exec-1",
                        seq=1,
                        channel=TradeChannel.CTP,
                        operation="place_order",
                        symbol="BTCUSDT",
                        metadata={"order_id": "oid-1"},
                        decision=AccountControlDecision.ALLOWED,
                        counted=True,
                        outcome="submitted",
                        event_uid="event-allowed",
                        occurred_at_ms=1_763_202_660_100,
                    ),
                    AccountControlEventWrite(
                        account_id=account.id,
                        control_date="2026-03-22",
                        execution_id="exec-1",
                        seq=2,
                        channel=TradeChannel.CTP,
                        operation="place_order",
                        symbol="BTCUSDT",
                        metadata={},
                        decision=AccountControlDecision.BLOCKED,
                        counted=False,
                        outcome="policy_blocked",
                        event_uid="event-blocked",
                        occurred_at_ms=1_763_202_660_200,
                    ),
                    AccountControlEventWrite(
                        account_id=account.id,
                        control_date="2026-03-22",
                        execution_id="exec-1",
                        seq=3,
                        channel=TradeChannel.CTP,
                        operation="query_order",
                        symbol="BTCUSDT",
                        metadata={},
                        decision=AccountControlDecision.ALLOWED,
                        counted=True,
                        outcome="downstream_error",
                        event_uid="event-failed",
                        occurred_at_ms=1_763_202_660_300,
                    ),
                ],
            )

            persisted_events = (
                (await session.execute(select(AccountControlEvent).order_by(AccountControlEvent.id))).scalars().all()
            )
            persisted_deltas = (
                (await session.execute(select(AccountControlCounterDelta).order_by(AccountControlCounterDelta.id)))
                .scalars()
                .all()
            )

            assert [event.event_uid for event in persisted_events] == [
                "event-allowed",
                "event-blocked",
                "event-failed",
            ]
            assert persisted_events[0].decision == AccountControlDecision.ALLOWED
            assert persisted_events[0].occurred_at_ms == 1_763_202_660_100
            assert persisted_events[1].decision == AccountControlDecision.BLOCKED
            assert persisted_events[1].counted is False
            assert persisted_events[2].outcome == "downstream_error"
            assert [delta.delta_uid for delta in persisted_deltas] == [
                "delta-allowed-day",
                "delta-allowed-symbol",
            ]

    asyncio.run(scenario())


def test_flush_execution_records_is_idempotent() -> None:
    """同一 execution 的重复 flush 不应重复插入，也不应放大下一次基线。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account()
            session.add(account)
            await session.commit()
            assert account.id is not None

            store = _build_store(session)
            counter_deltas = [
                AccountControlCounterDeltaWrite(
                    account_id=account.id,
                    execution_id="exec-2",
                    control_date="2026-03-22",
                    bucket_type=AccountControlBucketType.DAY,
                    bucket_start="2026-03-22T00:00:00",
                    scope_type=AccountControlScopeType.ACCOUNT,
                    symbol=None,
                    operation="cancel_order",
                    delta_count=2,
                    delta_uid="delta-idempotent",
                )
            ]
            events = [
                AccountControlEventWrite(
                    account_id=account.id,
                    control_date="2026-03-22",
                    execution_id="exec-2",
                    seq=1,
                    channel=TradeChannel.CTP,
                    operation="cancel_order",
                    symbol="ETHUSDT",
                    metadata={"order_id": "oid-2"},
                    decision=AccountControlDecision.ALLOWED,
                    counted=True,
                    outcome="submitted",
                    event_uid="event-idempotent",
                    occurred_at_ms=1_763_202_660_400,
                )
            ]

            await store.flush_execution_records(counter_deltas=counter_deltas, events=events)
            await store.flush_execution_records(counter_deltas=counter_deltas, events=events)

            persisted_event_count = (
                (await session.execute(select(AccountControlEvent).where(AccountControlEvent.execution_id == "exec-2")))
                .scalars()
                .all()
            )
            persisted_delta_count = (
                (
                    await session.execute(
                        select(AccountControlCounterDelta).where(AccountControlCounterDelta.execution_id == "exec-2")
                    )
                )
                .scalars()
                .all()
            )
            snapshot = await store.load_daily_counters(account.id, "2026-03-22")

            assert len(persisted_event_count) == 1
            assert len(persisted_delta_count) == 1
            assert (
                snapshot.get_count(
                    bucket_type=AccountControlBucketType.DAY,
                    bucket_start="2026-03-22T00:00:00",
                    operation="cancel_order",
                )
                == 2
            )

    asyncio.run(scenario())


def test_load_recent_allowed_timestamps_reads_account_and_symbol_scopes() -> None:
    """执行开始时应能读取最近一次 allowed 且 counted 的毫秒时间。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account()
            session.add(account)
            await session.commit()
            assert account.id is not None

            session.add_all(
                [
                    AccountControlEvent(
                        account_id=account.id,
                        control_date="2026-03-21",
                        execution_id="exec-older",
                        seq=1,
                        channel=TradeChannel.CTP,
                        operation="place_order",
                        symbol="BTCUSDT",
                        metadata={"order_id": "oid-1"},
                        decision=AccountControlDecision.ALLOWED,
                        counted=True,
                        outcome="submitted",
                        event_uid="event-old-allowed",
                        created_at="2026-03-21T23:59:59",
                        occurred_at_ms=1_763_193_599_000,
                    ),
                    AccountControlEvent(
                        account_id=account.id,
                        control_date="2026-03-22",
                        execution_id="exec-blocked",
                        seq=2,
                        channel=TradeChannel.CTP,
                        operation="place_order",
                        symbol="BTCUSDT",
                        metadata={},
                        decision=AccountControlDecision.BLOCKED,
                        counted=False,
                        outcome="policy_blocked",
                        event_uid="event-blocked",
                        created_at="2026-03-22T09:31:00",
                        occurred_at_ms=1_763_226_660_000,
                    ),
                    AccountControlEvent(
                        account_id=account.id,
                        control_date="2026-03-22",
                        execution_id="exec-account-query",
                        seq=3,
                        channel=TradeChannel.CTP,
                        operation="query_order",
                        symbol=None,
                        metadata={},
                        decision=AccountControlDecision.ALLOWED,
                        counted=True,
                        outcome="submitted",
                        event_uid="event-query-allowed",
                        created_at="2026-03-22T09:31:01",
                        occurred_at_ms=1_763_226_661_000,
                    ),
                    AccountControlEvent(
                        account_id=account.id,
                        control_date="2026-03-22",
                        execution_id="exec-symbol-newer",
                        seq=4,
                        channel=TradeChannel.CTP,
                        operation="place_order",
                        symbol="BTCUSDT",
                        metadata={"order_id": "oid-2"},
                        decision=AccountControlDecision.ALLOWED,
                        counted=True,
                        outcome="submitted",
                        event_uid="event-new-allowed",
                        created_at="2026-03-22T09:31:02",
                        occurred_at_ms=1_763_226_662_000,
                    ),
                ]
            )
            await session.commit()

            snapshot = await _build_store(session).load_recent_allowed_timestamps(account.id)

            assert snapshot.get_last_allowed_at_ms("query_order") == 1_763_226_661_000
            assert snapshot.get_last_allowed_at_ms("place_order") == 1_763_226_662_000
            assert (
                snapshot.get_last_allowed_at_ms(
                    "place_order",
                    symbol="BTCUSDT",
                )
                == 1_763_226_662_000
            )
            assert (
                snapshot.get_last_allowed_at_ms(
                    "place_order",
                    symbol="ETHUSDT",
                )
                is None
            )

    asyncio.run(scenario())

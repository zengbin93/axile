"""账户控制审计查询服务测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.models import AccountControlDecision
from axile.server import account_control_audit
from axile.server.db.models import Account, AccountControlEvent


def _build_account(*, account_id: int, name: str) -> Account:
    return Account(
        id=account_id,
        name=name,
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


class _RecordingSession:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.statements: list[str] = []

    async def execute(self, statement: object, *args: object, **kwargs: object) -> object:
        self.statements.append(str(statement))
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._session, name)


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


async def _seed_events(session: AsyncSession) -> None:
    session.add_all(
        [
            _build_account(account_id=1, name="primary"),
            _build_account(account_id=2, name="secondary"),
            AccountControlEvent(
                account_id=1,
                control_date="2026-03-22",
                execution_id="exec-newer",
                seq=2,
                channel=TradeChannel.CTP,
                operation="cancel_order",
                symbol="ag2612",
                metadata_={},
                decision=AccountControlDecision.ALLOWED,
                counted=True,
                outcome="downstream_error",
                event_uid="event-exec-newer-2",
                created_at="2026-03-22T09:35:00",
            ),
            AccountControlEvent(
                account_id=1,
                control_date="2026-03-22",
                execution_id="exec-newer",
                seq=1,
                channel=TradeChannel.CTP,
                operation="place_order",
                symbol="rb2610",
                metadata_={"order_id": "oid-1"},
                decision=AccountControlDecision.ALLOWED,
                counted=True,
                outcome="submitted",
                event_uid="event-exec-newer-1",
                created_at="2026-03-22T09:34:00",
            ),
            AccountControlEvent(
                account_id=1,
                control_date="2026-03-22",
                execution_id="exec-newer",
                seq=3,
                channel=TradeChannel.CTP,
                operation="place_order",
                symbol="rb2610",
                metadata_={},
                decision=AccountControlDecision.BLOCKED,
                counted=False,
                outcome="policy_blocked",
                event_uid="event-exec-newer-3",
                created_at="2026-03-22T09:36:00",
            ),
            AccountControlEvent(
                account_id=1,
                control_date="2026-03-22",
                execution_id="exec-older",
                seq=1,
                channel=TradeChannel.CTP,
                operation="query_order",
                symbol="rb2610",
                metadata_={},
                decision=AccountControlDecision.ALLOWED,
                counted=True,
                outcome="filled",
                event_uid="event-exec-older-1",
                created_at="2026-03-22T09:32:00",
            ),
            AccountControlEvent(
                account_id=1,
                control_date="2026-03-21",
                execution_id="exec-other-date",
                seq=1,
                channel=TradeChannel.CTP,
                operation="place_order",
                symbol="rb2610",
                metadata_={},
                decision=AccountControlDecision.ALLOWED,
                counted=True,
                outcome="submitted",
                event_uid="event-other-date",
                created_at="2026-03-21T09:32:00",
            ),
            AccountControlEvent(
                account_id=2,
                control_date="2026-03-22",
                execution_id="exec-other-account",
                seq=1,
                channel=TradeChannel.CTP,
                operation="place_order",
                symbol="rb2610",
                metadata_={},
                decision=AccountControlDecision.ALLOWED,
                counted=True,
                outcome="submitted",
                event_uid="event-other-account",
                created_at="2026-03-22T09:37:00",
            ),
        ]
    )
    await session.commit()


def test_query_account_control_audit_summary_aggregates_by_operation_decision_and_outcome() -> None:
    """账户日汇总应只基于事件表分组统计。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed_events(session)
            recording_session = _RecordingSession(session)

            rows = await account_control_audit.query_account_control_audit_summary(
                recording_session,
                account_id=1,
                control_date="2026-03-22",
            )

            assert [(row.operation, row.decision, row.outcome, row.count) for row in rows] == [
                ("cancel_order", AccountControlDecision.ALLOWED, "downstream_error", 1),
                ("place_order", AccountControlDecision.ALLOWED, "submitted", 1),
                ("place_order", AccountControlDecision.BLOCKED, "policy_blocked", 1),
                ("query_order", AccountControlDecision.ALLOWED, "filled", 1),
            ]
            assert recording_session.statements
            assert all("account_control_event" in stmt.lower() for stmt in recording_session.statements)

    asyncio.run(scenario())


def test_query_account_control_audit_executions_returns_recent_first_with_counts_and_window() -> None:
    """账户日 execution 列表应按最近事件倒序并返回首尾时间。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed_events(session)

            page = await account_control_audit.query_account_control_audit_executions(
                session,
                account_id=1,
                control_date="2026-03-22",
                skip=0,
                limit=1,
            )

            assert page.count == 2
            assert len(page.data) == 1
            assert page.data[0].execution_id == "exec-newer"
            assert page.data[0].event_count == 3
            assert page.data[0].first_event_at == "2026-03-22T09:34:00"
            assert page.data[0].last_event_at == "2026-03-22T09:36:00"

    asyncio.run(scenario())


def test_query_account_control_execution_events_supports_filters_and_stable_seq_order() -> None:
    """execution 事件流应支持 symbol 和 operation 过滤，并按 seq、id 稳定排序。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed_events(session)
            recording_session = _RecordingSession(session)

            page = await account_control_audit.query_account_control_execution_events(
                recording_session,
                execution_id="exec-newer",
                symbol="rb2610",
                operation="place_order",
                skip=0,
                limit=10,
            )

            assert page.count == 2
            assert [event.seq for event in page.data] == [1, 3]
            assert [event.outcome for event in page.data] == ["submitted", "policy_blocked"]
            assert recording_session.statements
            assert all("account_control_event" in stmt.lower() for stmt in recording_session.statements)

    asyncio.run(scenario())


def test_query_account_control_audit_service_rejects_limit_above_upper_bound() -> None:
    """服务层应固定分页上限，避免一次读取整日全量事件。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed_events(session)

            with pytest.raises(ValueError, match="limit"):
                await account_control_audit.query_account_control_audit_executions(
                    session,
                    account_id=1,
                    control_date="2026-03-22",
                    limit=501,
                )

            with pytest.raises(ValueError, match="limit"):
                await account_control_audit.query_account_control_execution_events(
                    session,
                    execution_id="exec-newer",
                    limit=501,
                )

    asyncio.run(scenario())


def test_query_account_control_audit_summary_keeps_min_interval_outcome_distinct() -> None:
    """最小间隔阻断应单独保留 outcome，不能混成普通 policy_blocked。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            session.add(_build_account(account_id=3, name="interval"))
            session.add(
                AccountControlEvent(
                    account_id=3,
                    control_date="2026-03-22",
                    execution_id="exec-interval",
                    seq=1,
                    channel=TradeChannel.CTP,
                    operation="place_order",
                    symbol="rb2610",
                    metadata_={},
                    decision=AccountControlDecision.BLOCKED,
                    counted=False,
                    outcome="policy_blocked_min_interval",
                    event_uid="event-interval-blocked",
                    created_at="2026-03-22T09:40:00",
                    occurred_at_ms=1_763_226_700_000,
                )
            )
            await session.commit()

            rows = await account_control_audit.query_account_control_audit_summary(
                session,
                account_id=3,
                control_date="2026-03-22",
            )

            assert [(row.operation, row.decision, row.outcome, row.count) for row in rows] == [
                (
                    "place_order",
                    AccountControlDecision.BLOCKED,
                    "policy_blocked_min_interval",
                    1,
                )
            ]

    asyncio.run(scenario())

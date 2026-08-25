"""自动排程的日历判断、预览与统一活动流测试。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.common.trade_channel import TradeChannel
from axile.server.api.routes import account_schedule
from axile.server.cron import SCHEDULER_TIMEZONE, parse_cron_expr
from axile.server.db.models import ExecuteRecord, ExecutionActivity, ScheduleSkip, ScheduleSkipActivity
from axile.server.execution import rebalance as rebalance_execution
from axile.server.execution import scheduler as execution_scheduler
from axile.server.trading_calendar import (
    CalendarDayDecision,
    CalendarDecisionStatus,
    CalendarUnavailableReason,
)


class _SessionContext:
    def __init__(
        self,
        account: object | None = None,
        *,
        added: list[object] | None = None,
        fail_commit: bool = False,
    ) -> None:
        self.account = account
        self.added = added if added is not None else []
        self.fail_commit = fail_commit

    async def __aenter__(self) -> "_SessionContext":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, _model: object, _key: object) -> object | None:
        return self.account

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("database unavailable")


def _account() -> SimpleNamespace:
    return SimpleNamespace(id=7, is_started=True, cron_expr="30 9 * * *", trade_channel=TradeChannel.CTP)


def _decision(
    status: CalendarDecisionStatus,
    reason: CalendarUnavailableReason | None = None,
) -> CalendarDayDecision:
    return CalendarDayDecision(
        channel="ctp",
        day=date(2026, 8, 24),
        calendar_id="china",
        label="中国交易日历",
        status=status,
        unavailable_reason=reason,
    )


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (CalendarDecisionStatus.NOT_REQUIRED, None),
        (CalendarDecisionStatus.AVAILABLE_OPEN, None),
        (CalendarDecisionStatus.UNAVAILABLE, CalendarUnavailableReason.NOT_CONFIGURED),
        (CalendarDecisionStatus.UNAVAILABLE, CalendarUnavailableReason.UNCOVERED),
        (CalendarDecisionStatus.UNAVAILABLE, CalendarUnavailableReason.READ_FAILED),
    ],
)
def test_scheduled_rebalance_executes_unless_calendar_is_explicitly_closed(
    monkeypatch: pytest.MonkeyPatch,
    status: CalendarDecisionStatus,
    reason: CalendarUnavailableReason | None,
) -> None:
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: _SessionContext(_account()))

    async def evaluate(*_args: object) -> CalendarDayDecision:
        return _decision(status, reason)

    executions: list[tuple[object, ...]] = []

    async def execute_trade(*args: object) -> None:
        executions.append(args)

    monkeypatch.setattr(execution_scheduler, "evaluate_channel_calendar_moment", evaluate)
    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)

    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    assert executions == [(7, None, "scheduler")]


@pytest.mark.parametrize("fail_commit", [False, True])
def test_closed_day_never_executes_even_if_skip_record_fails(
    monkeypatch: pytest.MonkeyPatch,
    fail_commit: bool,
) -> None:
    added: list[object] = []
    sessions = iter(
        [
            _SessionContext(_account()),
            _SessionContext(added=added, fail_commit=fail_commit),
        ]
    )
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: next(sessions))

    async def evaluate(*_args: object) -> CalendarDayDecision:
        return _decision(CalendarDecisionStatus.AVAILABLE_CLOSED)

    execute_trade = MagicMock()
    monkeypatch.setattr(execution_scheduler, "evaluate_channel_calendar_moment", evaluate)
    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)

    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))

    execute_trade.assert_not_called()
    assert len(added) == 1
    record = added[0]
    assert isinstance(record, ScheduleSkip)
    assert record.reason_code == "CALENDAR.CLOSED"
    assert record.calendar_id == "china"


def test_calendar_evaluation_exception_is_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: _SessionContext(_account()))

    async def evaluate(*_args: object) -> CalendarDayDecision:
        raise RuntimeError("unexpected calendar failure")

    executions: list[tuple[object, ...]] = []

    async def execute_trade(*args: object) -> None:
        executions.append(args)

    monkeypatch.setattr(execution_scheduler, "evaluate_channel_calendar_moment", evaluate)
    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    assert executions == [(7, None, "scheduler")]


def test_scheduled_rebalance_ignores_stale_job_for_stopped_account(monkeypatch: pytest.MonkeyPatch) -> None:
    account = SimpleNamespace(is_started=False, cron_expr="30 9 * * *", trade_channel=TradeChannel.CTP)
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: _SessionContext(account))

    async def evaluate(*_args: object) -> CalendarDayDecision:
        raise AssertionError("stopped account must not evaluate calendar")

    monkeypatch.setattr(execution_scheduler, "evaluate_channel_calendar_moment", evaluate)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))


def test_create_job_targets_calendar_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    account = SimpleNamespace(id=7, name="测试账户", is_started=True, trade_channel=TradeChannel.CTP)
    scheduler = SimpleNamespace(add_job=MagicMock())
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: _SessionContext(account))

    async def portfolio_id(*_args: object) -> int:
        return 11

    monkeypatch.setattr(execution_scheduler, "get_latest_portfolio_id_by_account_id", portfolio_id)
    asyncio.run(execution_scheduler.create_job(scheduler, account, parse_cron_expr("30 9 * * *")))
    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs["func"] is execution_scheduler.execute_scheduled_rebalance
    assert kwargs["args"] == [7]
    assert kwargs["next_run_time"].tzinfo == SCHEDULER_TIMEZONE


def test_next_schedule_times_deduplicates_and_uses_beijing_timezone() -> None:
    start = datetime(2026, 8, 23, 8, 0, tzinfo=SCHEDULER_TIMEZONE)
    values = account_schedule._next_schedule_times(
        parse_cron_expr("30 9 * * * | 30 9 * * *"),
        start=start,
        limit=3,
    )
    assert [value.isoformat() for value in values] == [
        "2026-08-23T09:30:00+08:00",
        "2026-08-24T09:30:00+08:00",
        "2026-08-25T09:30:00+08:00",
    ]


def test_schedule_preview_maps_only_closed_to_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    closed_at = datetime(2026, 8, 24, 9, 30, tzinfo=SCHEDULER_TIMEZONE)
    unavailable_at = datetime(2026, 8, 25, 9, 30, tzinfo=SCHEDULER_TIMEZONE)
    monkeypatch.setattr(account_schedule, "_next_schedule_times", lambda *_args, **_kwargs: [closed_at, unavailable_at])

    async def summary(*_args: object) -> account_schedule.SchedulePreviewCalendar:
        return account_schedule.SchedulePreviewCalendar(
            requirement="required",
            availability="unavailable",
            unavailable_reason=CalendarUnavailableReason.UNCOVERED,
            calendar_id="china",
            label="中国交易日历",
        )

    async def decision(_session: object, _channel: object, current: datetime) -> CalendarDayDecision:
        if current.date() == closed_at.date():
            return _decision(CalendarDecisionStatus.AVAILABLE_CLOSED)
        return CalendarDayDecision(
            channel="ctp",
            day=unavailable_at.date(),
            calendar_id="china",
            status=CalendarDecisionStatus.UNAVAILABLE,
            unavailable_reason=CalendarUnavailableReason.UNCOVERED,
        )

    monkeypatch.setattr(account_schedule, "_calendar_summary", summary)
    monkeypatch.setattr(account_schedule, "evaluate_channel_calendar_moment", decision)
    response = asyncio.run(
        account_schedule.schedule_preview(
            object(),  # type: ignore[arg-type]
            account_schedule.SchedulePreviewRequest(
                trade_channel=TradeChannel.CTP,
                cron_expr="30 9 * * *",
                limit=2,
            ),
        )
    )
    assert [item.action for item in response.items] == ["skip", "execute"]
    assert response.items[1].unavailable_reason is CalendarUnavailableReason.UNCOVERED


async def _create_database(path: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def test_activity_merges_sorts_and_pages_across_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "activity.db"))

    async def account_exists(*_args: object) -> object:
        return SimpleNamespace(id=7)

    monkeypatch.setattr(account_schedule, "_get_account_or_404", account_exists)

    async def exercise() -> account_schedule.AccountActivityListPublic:
        async with session_factory() as session:
            session.add_all(
                [
                    ExecuteRecord(
                        execution_id="exec-new",
                        account_id=7,
                        created_at="2026-08-24T12:00:00+08:00",
                        raw_input={},
                        raw_result={},
                        is_success=1,
                    ),
                    ExecuteRecord(
                        execution_id="exec-old",
                        account_id=7,
                        created_at="2026-08-24T10:00:00+08:00",
                        raw_input={},
                        raw_result={},
                        is_success=0,
                    ),
                    ScheduleSkip(
                        account_id=7,
                        channel="ctp",
                        triggered_at="2026-08-24T11:00:00+08:00",
                        calendar_id="china",
                        calendar_day=date(2026, 8, 24),
                        calendar_label="中国交易日历",
                    ),
                    ScheduleSkip(
                        account_id=7,
                        channel="ctp",
                        triggered_at="2026-08-24T09:00:00+08:00",
                        calendar_id="china",
                        calendar_day=date(2026, 8, 24),
                        calendar_label="中国交易日历",
                    ),
                ]
            )
            await session.commit()
            return await account_schedule.account_activity(session, 7, skip=1, limit=2)

    result = asyncio.run(exercise())
    assert result.count == 4
    assert [item.kind for item in result.data] == ["schedule_skip", "execution"]
    assert isinstance(result.data[0], ScheduleSkipActivity)
    assert isinstance(result.data[1], ExecutionActivity)
    assert result.data[1].record.execution_id == "exec-old"


def test_schedule_preview_models_enforce_limits_and_serialize_timezone() -> None:
    with pytest.raises(ValueError):
        account_schedule.SchedulePreviewRequest(
            trade_channel=TradeChannel.CTP,
            cron_expr="30 9 * * *",
            limit=11,
        )
    response = account_schedule.SchedulePreviewResponse(
        evaluated_at=datetime(2026, 8, 23, 8, 0, tzinfo=SCHEDULER_TIMEZONE),
        calendar=account_schedule.SchedulePreviewCalendar(
            requirement="required",
            availability="unavailable",
            unavailable_reason=CalendarUnavailableReason.NOT_CONFIGURED,
        ),
        items=[],
    )
    payload: dict[str, Any] = response.model_dump(mode="json")
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["evaluated_at"].endswith("+08:00")

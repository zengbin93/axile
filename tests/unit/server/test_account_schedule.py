"""自动排程预览与触发测试。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from axile.common.trade_channel import TradeChannel
from axile.server.api.routes import account_schedule
from axile.server.cron import SCHEDULER_TIMEZONE, parse_cron_expr
from axile.server.execution import rebalance as rebalance_execution
from axile.server.execution import scheduler as execution_scheduler
from axile.server.trading_calendar import (
    CalendarDayDecision,
    CalendarDecisionStatus,
    CalendarUnavailableReason,
)


class _SessionContext:
    def __init__(self, account: object | None = None) -> None:
        self.account = account
        self.added: list[object] = []
        self.commit_error: Exception | None = None

    async def __aenter__(self) -> "_SessionContext":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, _model: object, _key: object) -> object | None:
        return self.account

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error


def _account(*, started: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        name="测试账户",
        is_started=started,
        cron_expr="30 9 * * *",
        trade_channel=TradeChannel.CTP,
    )


def _decision(status: CalendarDecisionStatus) -> CalendarDayDecision:
    return CalendarDayDecision(
        channel="ctp",
        day=date(2026, 8, 29),
        status=status,
        calendar_id="china",
        label="中国交易日历",
        unavailable_reason=(
            CalendarUnavailableReason.UNCOVERED if status is CalendarDecisionStatus.UNAVAILABLE else None
        ),
        reason_code=("CALENDAR.CLOSED" if status is CalendarDecisionStatus.AVAILABLE_CLOSED else None),
    )


def test_scheduled_rebalance_delegates_on_open_day(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SessionContext(_account())
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        execution_scheduler,
        "evaluate_channel_calendar_moment",
        lambda *_args: _decision(CalendarDecisionStatus.AVAILABLE_OPEN),
    )
    executions: list[tuple[object, ...]] = []

    async def execute_trade(*args: object) -> None:
        executions.append(args)

    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    assert executions == [(7, None, "scheduler")]


def test_scheduled_rebalance_skips_closed_day_and_records_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SessionContext(_account())
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        execution_scheduler,
        "evaluate_channel_calendar_moment",
        lambda *_args: _decision(CalendarDecisionStatus.AVAILABLE_CLOSED),
    )
    execute_trade = MagicMock()
    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)

    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))

    execute_trade.assert_not_called()
    assert len(session.added) == 1
    assert getattr(session.added[0], "reason_code") == "CALENDAR.CLOSED"


def test_scheduled_rebalance_is_fail_open_when_calendar_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SessionContext(_account())
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        execution_scheduler,
        "evaluate_channel_calendar_moment",
        lambda *_args: _decision(CalendarDecisionStatus.UNAVAILABLE),
    )
    executions: list[tuple[object, ...]] = []

    async def execute_trade(*args: object) -> None:
        executions.append(args)

    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    assert executions == [(7, None, "scheduler")]
    assert session.added == []


def test_closed_day_stays_skipped_when_audit_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SessionContext(_account())
    session.commit_error = RuntimeError("database unavailable")
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        execution_scheduler,
        "evaluate_channel_calendar_moment",
        lambda *_args: _decision(CalendarDecisionStatus.AVAILABLE_CLOSED),
    )
    execute_trade = MagicMock()
    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    execute_trade.assert_not_called()


def test_scheduled_rebalance_ignores_stale_job_for_stopped_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: _SessionContext(_account(started=False)))
    execute_trade = MagicMock()
    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    execute_trade.assert_not_called()


def test_create_job_targets_scheduler_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account()
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


def test_schedule_preview_returns_raw_cron_points_with_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    evaluated = datetime(2026, 8, 26, 9, 0, tzinfo=SCHEDULER_TIMEZONE)

    class _Datetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return evaluated

    monkeypatch.setattr(account_schedule, "datetime", _Datetime)
    payload = account_schedule.SchedulePreviewRequest(
        trade_channel=TradeChannel.CTP,
        cron_expr="30 9 * * *",
        limit=2,
    )
    response = asyncio.run(account_schedule.schedule_preview(payload))
    assert [item.scheduled_at.isoformat() for item in response.items] == [
        "2026-08-26T09:30:00+08:00",
        "2026-08-27T09:30:00+08:00",
    ]
    assert response.next_cursor == response.items[-1].scheduled_at
    assert response.has_more is True

    continued = asyncio.run(
        account_schedule.schedule_preview(payload.model_copy(update={"after": response.next_cursor}))
    )
    assert continued.items[0].scheduled_at.isoformat() == "2026-08-28T09:30:00+08:00"


def test_schedule_preview_keeps_weekend_points_and_marks_them_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    evaluated = datetime(2026, 8, 28, 15, 1, tzinfo=SCHEDULER_TIMEZONE)

    class _Datetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return evaluated

    monkeypatch.setattr(account_schedule, "datetime", _Datetime)
    response = asyncio.run(
        account_schedule.schedule_preview(
            account_schedule.SchedulePreviewRequest(
                trade_channel=TradeChannel.CTP,
                cron_expr="0 10 * * *",
                limit=3,
            )
        )
    )

    assert [item.calendar_day for item in response.items] == [
        date(2026, 8, 29),
        date(2026, 8, 30),
        date(2026, 8, 31),
    ]
    assert [item.action for item in response.items] == ["skip", "skip", "execute"]
    assert response.calendar.calendar_id == "china"


def test_schedule_preview_marks_unsupported_year_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    evaluated = datetime(2027, 1, 1, 8, 0, tzinfo=SCHEDULER_TIMEZONE)

    class _Datetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return evaluated

    monkeypatch.setattr(account_schedule, "datetime", _Datetime)
    response = asyncio.run(
        account_schedule.schedule_preview(
            account_schedule.SchedulePreviewRequest(
                trade_channel=TradeChannel.CTP,
                cron_expr="0 10 * * *",
                limit=1,
            )
        )
    )

    assert response.calendar.availability == "unavailable"
    assert response.calendar.unavailable_reason is CalendarUnavailableReason.UNCOVERED
    assert response.items[0].calendar_status is CalendarDecisionStatus.UNAVAILABLE
    assert response.items[0].action == "execute"


def test_schedule_preview_models_enforce_limits_and_timezone() -> None:
    with pytest.raises(ValidationError):
        account_schedule.SchedulePreviewRequest(
            trade_channel=TradeChannel.CTP,
            cron_expr="30 9 * * *",
            limit=101,
        )
    response = account_schedule.SchedulePreviewResponse(
        evaluated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        calendar=account_schedule.SchedulePreviewCalendar(
            requirement="required",
            availability="available",
            calendar_id="china",
            label="中国交易日历",
        ),
        items=[
            account_schedule.SchedulePreviewItem(
                scheduled_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
                calendar_day=date(2026, 8, 27),
                calendar_status=CalendarDecisionStatus.AVAILABLE_OPEN,
                action="execute",
                calendar_id="china",
                label="中国交易日历",
            )
        ],
    )
    assert response.timezone == "Asia/Shanghai"

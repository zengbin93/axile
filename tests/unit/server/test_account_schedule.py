"""自动排程预览与触发测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from axile.common.trade_channel import TradeChannel
from axile.server.api.routes import account_schedule
from axile.server.cron import SCHEDULER_TIMEZONE, parse_cron_expr
from axile.server.execution import rebalance as rebalance_execution
from axile.server.execution import scheduler as execution_scheduler


class _SessionContext:
    def __init__(self, account: object | None = None) -> None:
        self.account = account

    async def __aenter__(self) -> "_SessionContext":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, _model: object, _key: object) -> object | None:
        return self.account


def _account(*, started: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        name="测试账户",
        is_started=started,
        cron_expr="30 9 * * *",
        trade_channel=TradeChannel.CTP,
    )


def test_scheduled_rebalance_always_delegates_to_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_scheduler, "SessionLocal", lambda: _SessionContext(_account()))
    executions: list[tuple[object, ...]] = []

    async def execute_trade(*args: object) -> None:
        executions.append(args)

    monkeypatch.setattr(rebalance_execution, "execute_trade", execute_trade)
    asyncio.run(execution_scheduler.execute_scheduled_rebalance(7))
    assert executions == [(7, None, "scheduler")]


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


def test_schedule_preview_models_enforce_limits_and_timezone() -> None:
    with pytest.raises(ValidationError):
        account_schedule.SchedulePreviewRequest(
            trade_channel=TradeChannel.CTP,
            cron_expr="30 9 * * *",
            limit=101,
        )
    response = account_schedule.SchedulePreviewResponse(
        evaluated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        items=[account_schedule.SchedulePreviewItem(scheduled_at=datetime(2026, 8, 27, tzinfo=timezone.utc))],
    )
    assert response.timezone == "Asia/Shanghai"

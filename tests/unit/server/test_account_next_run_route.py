"""账户 next_run_time 路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from types import SimpleNamespace

import pytest
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.server.api.deps import get_db, get_scheduler
from axile.server.api.routes import account as account_routes
from axile.server.api.routes import account_crud
from axile.server.db.models import Account
from axile.server.trading_calendar import CalendarDecisionStatus
from tests.unit.server._execution_test_support import build_account


class _RouteSession:
    def __init__(self, account: Account | None = None) -> None:
        self.account = account

    async def get(self, _model: object, account_id: int) -> Account | None:
        if self.account is not None and self.account.id == account_id:
            return self.account
        return None


class _Job:
    def __init__(self, next_run_time: datetime | None, trigger: object | None = None) -> None:
        self.next_run_time = next_run_time
        self.trigger = trigger


class _Scheduler:
    def __init__(self, job: _Job | None = None) -> None:
        self._job = job

    def get_job(self, _job_id: str) -> _Job | None:
        return self._job


def _build_app(session: _RouteSession, scheduler: _Scheduler) -> FastAPI:
    app = FastAPI()
    app.include_router(account_routes.router)

    async def _override_get_db() -> AsyncGenerator[_RouteSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    return app


@pytest.fixture(autouse=True)
def _calendar_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认模拟无需交易日历的渠道，专门用例再覆盖判定。"""

    async def evaluate(_session: object, _channel: object, days: list[object]) -> dict[object, SimpleNamespace]:
        return {day: SimpleNamespace(status=CalendarDecisionStatus.NOT_REQUIRED) for day in days}

    monkeypatch.setattr(account_crud, "evaluate_channel_calendar_days", evaluate)


def test_next_run_time_returns_iso_when_job_scheduled() -> None:
    """存在调度任务时返回未来三次，并保留单值字段兼容调用方。"""
    timezone = "Asia/Shanghai"
    trigger = CronTrigger(hour=9, minute=3, timezone=timezone)
    next_run = datetime.fromisoformat("2026-07-02T09:03:00+08:00")
    app = _build_app(_RouteSession(build_account(id=1)), _Scheduler(_Job(next_run, trigger)))

    response = TestClient(app).get("/account/1/next_run_time")

    assert response.status_code == 200
    assert response.json() == {
        "account_id": 1,
        "is_scheduled": True,
        "next_run_time": next_run.isoformat(),
        "next_run_times": [
            "2026-07-02T09:03:00+08:00",
            "2026-07-03T09:03:00+08:00",
            "2026-07-04T09:03:00+08:00",
        ],
        "next_execution_times": [
            "2026-07-02T09:03:00+08:00",
            "2026-07-03T09:03:00+08:00",
            "2026-07-04T09:03:00+08:00",
        ],
    }


def test_next_run_times_merge_multiple_cron_rules_in_order() -> None:
    """组合触发器跨日展开时保持去重与升序。"""
    timezone = "Asia/Shanghai"
    trigger = OrTrigger(
        [
            CronTrigger(hour=10, minute=0, timezone=timezone),
            CronTrigger(hour=15, minute=0, timezone=timezone),
        ]
    )
    next_run = datetime.fromisoformat("2026-07-02T10:00:00+08:00")
    app = _build_app(_RouteSession(build_account(id=1)), _Scheduler(_Job(next_run, trigger)))

    response = TestClient(app).get("/account/1/next_run_time")

    assert response.status_code == 200
    assert response.json()["next_run_times"] == [
        "2026-07-02T10:00:00+08:00",
        "2026-07-02T15:00:00+08:00",
        "2026-07-03T10:00:00+08:00",
    ]


def test_next_execution_times_skip_closed_calendar_days(monkeypatch: pytest.MonkeyPatch) -> None:
    """明确休市的触发点不进入实际执行时间表，并继续向后补满三次。"""
    trigger = CronTrigger(hour=10, minute=0, timezone="Asia/Shanghai")
    next_run = datetime.fromisoformat("2026-07-03T10:00:00+08:00")  # 周五

    async def evaluate(_session: object, _channel: object, days: list[object]) -> dict[object, SimpleNamespace]:
        return {
            day: SimpleNamespace(
                status=(
                    CalendarDecisionStatus.AVAILABLE_CLOSED
                    if str(day) in {"2026-07-03", "2026-07-04", "2026-07-05"}
                    else CalendarDecisionStatus.AVAILABLE_OPEN
                )
            )
            for day in days
        }

    monkeypatch.setattr(account_crud, "evaluate_channel_calendar_days", evaluate)
    app = _build_app(_RouteSession(build_account(id=1)), _Scheduler(_Job(next_run, trigger)))

    response = TestClient(app).get("/account/1/next_run_time")

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_run_time"] == "2026-07-03T10:00:00+08:00"
    assert payload["next_execution_times"] == [
        "2026-07-06T10:00:00+08:00",
        "2026-07-07T10:00:00+08:00",
        "2026-07-08T10:00:00+08:00",
    ]


def test_next_execution_times_fail_open_when_calendar_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """交易日历不可用时与真实调度一致，保留原始触发时间。"""
    trigger = CronTrigger(hour=10, minute=0, timezone="Asia/Shanghai")
    next_run = datetime.fromisoformat("2026-07-03T10:00:00+08:00")

    async def evaluate(_session: object, _channel: object, days: list[object]) -> dict[object, SimpleNamespace]:
        return {day: SimpleNamespace(status=CalendarDecisionStatus.UNAVAILABLE) for day in days}

    monkeypatch.setattr(account_crud, "evaluate_channel_calendar_days", evaluate)
    app = _build_app(_RouteSession(build_account(id=1)), _Scheduler(_Job(next_run, trigger)))

    response = TestClient(app).get("/account/1/next_run_time")

    assert response.status_code == 200
    assert response.json()["next_execution_times"] == response.json()["next_run_times"]


def test_next_run_time_null_when_no_job() -> None:
    """账户存在但无调度任务时，is_scheduled=False 且 next_run_time 为 None。"""
    app = _build_app(_RouteSession(build_account(id=1)), _Scheduler(job=None))

    response = TestClient(app).get("/account/1/next_run_time")

    assert response.status_code == 200
    assert response.json() == {
        "account_id": 1,
        "is_scheduled": False,
        "next_run_time": None,
        "next_run_times": [],
        "next_execution_times": [],
    }


def test_next_run_time_null_when_job_has_no_next_fire() -> None:
    """任务存在但已暂停（next_run_time 为 None）时，is_scheduled=True 且时间为 None。"""
    app = _build_app(_RouteSession(build_account(id=1)), _Scheduler(_Job(None)))

    response = TestClient(app).get("/account/1/next_run_time")

    assert response.status_code == 200
    assert response.json() == {
        "account_id": 1,
        "is_scheduled": True,
        "next_run_time": None,
        "next_run_times": [],
        "next_execution_times": [],
    }


def test_next_run_time_404_when_account_missing() -> None:
    """账户不存在时返回 404。"""
    app = _build_app(_RouteSession(account=None), _Scheduler(_Job(datetime(2026, 7, 2, 9, 3, 0))))

    response = TestClient(app).get("/account/999/next_run_time")

    assert response.status_code == 404

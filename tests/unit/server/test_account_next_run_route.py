"""账户 next_run_time 路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.server.api.deps import get_db, get_scheduler
from axile.server.api.routes import account as account_routes
from axile.server.db.models import Account
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
    }


def test_next_run_time_404_when_account_missing() -> None:
    """账户不存在时返回 404。"""
    app = _build_app(_RouteSession(account=None), _Scheduler(_Job(datetime(2026, 7, 2, 9, 3, 0))))

    response = TestClient(app).get("/account/999/next_run_time")

    assert response.status_code == 404

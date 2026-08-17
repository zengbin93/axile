"""服务端辅助模块测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from axile.server import initial_data
from axile.server.api import deps
from axile.server.api.routes import utils as route_utils
from axile.server.core import std_log_config


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def execute(self, _statement: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(self._rows)


class _FakeSessionContext:
    def __init__(self, rows: list[object]) -> None:
        self.session = _FakeSession(rows)

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def test_health_check_returns_true() -> None:
    """应返回 API 路由的简单存活信号。"""
    assert route_utils.health_check() is True


def test_get_scheduler_returns_shared_scheduler_instance() -> None:
    """应返回进程级共享的调度器单例。"""
    assert deps.get_scheduler() is deps.scheduler


def test_get_db_yields_session_from_sessionlocal(monkeypatch: pytest.MonkeyPatch) -> None:
    """应为当前请求产出由 SessionLocal 创建的会话。"""
    expected_session = object()

    class _FakeDbContext:
        async def __aenter__(self) -> object:
            return expected_session

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    monkeypatch.setattr(deps, "SessionLocal", lambda: _FakeDbContext())

    async def scenario() -> None:
        generator = deps.get_db()
        yielded = await generator.__anext__()
        assert yielded is expected_session
        await generator.aclose()

    asyncio.run(scenario())


def test_init_scheduler_recreates_jobs_for_all_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """启动期间应根据已持久化账户重建调度任务；空 cron 跳过."""
    account_a = SimpleNamespace(cron_expr="*/5 * * * *")
    account_b = SimpleNamespace(cron_expr="0 * * * *")
    account_blank = SimpleNamespace(cron_expr="")
    create_calls: list[tuple[object, object, list[str]]] = []

    monkeypatch.setattr(
        initial_data,
        "SessionLocal",
        lambda: _FakeSessionContext([account_a, account_blank, account_b]),
    )
    monkeypatch.setattr(initial_data, "parse_cron_expr", lambda expr: [f"parsed:{expr}"])

    async def fake_create_job(scheduler: object, account: object, cron_expr: list[str]) -> None:
        create_calls.append((scheduler, account, cron_expr))

    monkeypatch.setattr(initial_data, "create_job", fake_create_job)

    asyncio.run(initial_data.init_scheduler())

    assert create_calls == [
        (initial_data.scheduler, account_a, ["parsed:*/5 * * * *"]),
        (initial_data.scheduler, account_b, ["parsed:0 * * * *"]),
    ]


def test_setup_std_logging_returns_and_applies_log_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """应构造预期的日志配置并传给 logging.config.dictConfig。"""
    captured: dict[str, object] = {}

    monkeypatch.setattr(std_log_config.logging.config, "dictConfig", lambda config: captured.update(config))

    result = std_log_config.setup_std_logging()

    assert result["version"] == 1
    assert result["loggers"]["uvicorn.error"]["level"] == "INFO"
    assert captured == result

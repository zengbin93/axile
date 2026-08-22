"""本地交易日历的查询、同步与执行器降级测试。"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.executor.abstract_executor.execution_runtime_host import AbstractExecutorExecutionRuntimeHostMixin
from axile.executor.trading_calendar import SqliteTradingCalendar
from axile.server import trading_calendar as calendar_service
from axile.server.api.deps import get_db
from axile.server.api.routes.trading_calendar import router
from axile.server.db.models import TradingCalendarRecord


async def _create_database(path: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def test_calendar_route_matches_skz_contract(tmp_path: Path) -> None:
    database_path = tmp_path / "calendar.db"
    session_factory = asyncio.run(_create_database(database_path))

    async def seed() -> None:
        async with session_factory() as session:
            session.add_all(
                [
                    TradingCalendarRecord(
                        exchange="SSE",
                        cal_date=date(2026, 8, 22),
                        is_open=False,
                        pretrade_date=date(2026, 8, 21),
                    ),
                    TradingCalendarRecord(
                        exchange="SSE",
                        cal_date=date(2026, 8, 24),
                        is_open=True,
                        pretrade_date=date(2026, 8, 21),
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed())
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/trading-calendar",
            params={"exchange": "SSE", "start": "2026-08-20", "end": "2026-08-24", "onlyOpen": "true"},
        )
        invalid_range = client.get(
            "/api/v1/market/trading-calendar",
            params={"exchange": "SSE", "start": "2026-08-24", "end": "2026-08-20"},
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "exchange": "SSE",
            "calDate": "2026-08-24",
            "isOpen": True,
            "pretradeDate": "2026-08-21",
        }
    ]
    assert invalid_range.status_code == 422


def test_ensure_calendar_upserts_only_when_coverage_is_short(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "sync.db"))
    monkeypatch.setattr(calendar_service, "SessionLocal", session_factory)
    monkeypatch.setattr(calendar_service.settings, "trading_calendar_token", "sk_test")
    monkeypatch.setattr(calendar_service.settings, "trading_calendar_api", "https://calendar.test")
    calls: list[str] = []

    async def fake_fetch(exchange: str) -> list[calendar_service.TradingCalendarEntry]:
        calls.append(exchange)
        return [
            calendar_service.TradingCalendarEntry(
                exchange=exchange,
                cal_date=date.today() + timedelta(days=120),
                is_open=True,
                pretrade_date=date.today(),
            )
        ]

    monkeypatch.setattr(calendar_service, "_fetch_calendar", fake_fetch)
    asyncio.run(calendar_service.ensure_trading_calendar_coverage())
    asyncio.run(calendar_service.ensure_trading_calendar_coverage())

    assert sorted(calls) == ["CFFEX", "SSE"]


class _CalendarHost(AbstractExecutorExecutionRuntimeHostMixin):
    """只承载日历辅助方法的轻量测试宿主。"""


def test_executor_calendar_uses_database_and_falls_back_to_weekdays(tmp_path: Path) -> None:
    database_path = tmp_path / "reader.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE trading_calendar (exchange TEXT, cal_date DATE, is_open BOOLEAN, "
            "pretrade_date DATE, updated_at TEXT, PRIMARY KEY (exchange, cal_date))"
        )
        connection.execute(
            "INSERT INTO trading_calendar VALUES (?, ?, ?, ?, ?)",
            ("SSE", "2026-10-01", 0, "2026-09-30", "2026-08-22T00:00:00"),
        )

    host = object.__new__(_CalendarHost)
    host.logger = MagicMock()
    host._trading_calendar = SqliteTradingCalendar(database_path)

    assert host._is_exchange_open("SSE", date(2026, 10, 1)) is False
    assert host._is_exchange_open("SSE", date(2026, 10, 2)) is True
    assert host._is_exchange_open("SSE", date(2026, 10, 3)) is False
    host.logger.warning.assert_called()


def test_register_calendar_job_is_monthly() -> None:
    scheduler = SimpleNamespace(add_job=MagicMock())

    calendar_service.register_trading_calendar_job(scheduler)  # type: ignore[arg-type]

    scheduler.add_job.assert_called_once_with(
        calendar_service.ensure_trading_calendar_coverage,
        trigger="cron",
        day=1,
        hour=4,
        minute=0,
        id="ensure-trading-calendar",
        replace_existing=True,
    )

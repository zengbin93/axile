"""单基础交易日历、人工覆盖与刷新行为测试。"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from axile.executor.abstract_executor.execution_runtime_host import AbstractExecutorExecutionRuntimeHostMixin
from axile.executor.trading_calendar import SqliteTradingCalendar
from axile.server import trading_calendar as calendar_service
from axile.server.api.deps import get_db
from axile.server.api.routes.trading_calendar import router
from axile.server.db.models import TradingCalendarConfig, TradingCalendarOverride, TradingCalendarRecord


async def _create_database(path: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _calendar_app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture(autouse=True)
def _clear_sync_locks() -> None:
    calendar_service._SYNC_LOCKS.clear()


def test_calendar_route_returns_effective_values_and_minimal_diagnostics(tmp_path: Path) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "calendar.db"))

    async def seed() -> None:
        async with session_factory() as session:
            session.add_all(
                [
                    TradingCalendarRecord(calendar_id="china", cal_date=date(2026, 8, 21), is_open=True),
                    TradingCalendarRecord(calendar_id="china", cal_date=date(2026, 8, 22), is_open=False),
                    TradingCalendarRecord(calendar_id="china", cal_date=date(2026, 8, 23), is_open=False),
                    TradingCalendarRecord(calendar_id="china", cal_date=date(2026, 8, 24), is_open=True),
                    TradingCalendarOverride(calendar_id="china", cal_date=date(2026, 8, 22), is_open=True),
                ]
            )
            await session.commit()

    asyncio.run(seed())
    with TestClient(_calendar_app(session_factory)) as client:
        response = client.get(
            "/api/v1/market/trading-calendar",
            params={"calendarId": "china", "start": "2026-08-22", "end": "2026-08-24"},
        )
        diagnostics = client.get(
            "/api/v1/market/trading-calendar/diagnostics",
            params={"calendarId": "china", "start": "2026-08-22", "end": "2026-08-24"},
        )

    assert response.status_code == 200
    assert [row["isOpen"] for row in response.json()] == [True, False, True]
    assert [row["pretradeDate"] for row in response.json()] == ["2026-08-21", "2026-08-22", "2026-08-22"]
    assert diagnostics.json()[0] == {
        "calendarId": "china",
        "calDate": "2026-08-22",
        "baseIsOpen": False,
        "overrideIsOpen": True,
        "isOpen": True,
    }


def test_override_api_lists_and_restores_base_value(tmp_path: Path) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "overrides.db"))

    async def seed() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="china", cal_date=date(2026, 10, 1), is_open=False))
            session.add(TradingCalendarOverride(calendar_id="china", cal_date=date(2026, 10, 1), is_open=True))
            await session.commit()

    asyncio.run(seed())
    with TestClient(_calendar_app(session_factory)) as client:
        listed = client.get("/api/v1/market/trading-calendar/overrides")
        restored = client.post(
            "/api/v1/market/trading-calendar/overrides/restore",
            json={"calendarId": "china", "dates": ["2026-10-01"]},
        )
        diagnostics = client.get(
            "/api/v1/market/trading-calendar/diagnostics",
            params={"start": "2026-10-01", "end": "2026-10-01"},
        )

    assert listed.status_code == 200
    assert listed.json()[0] | {"updatedAt": "ignored"} == {
        "calendarId": "china",
        "calDate": "2026-10-01",
        "isOpen": True,
        "baseIsOpen": False,
        "updatedAt": "ignored",
    }
    assert restored.status_code == 200
    assert diagnostics.json()[0]["overrideIsOpen"] is None
    assert diagnostics.json()[0]["isOpen"] is False


def test_csv_preview_is_stateless_and_import_switches_source_atomically(tmp_path: Path) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "csv.db"))

    async def seed() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="vendor", cal_date=date(2026, 10, 1), is_open=False))
            session.add(TradingCalendarOverride(calendar_id="vendor", cal_date=date(2026, 10, 1), is_open=True))
            session.add(
                TradingCalendarConfig(
                    calendar_id="vendor",
                    refresh_kind="python",
                    function_code="def get_trading_calendar(calendar_id, start, end): return []",
                )
            )
            await session.commit()

    asyncio.run(seed())
    preview_content = b"calendar_id,cal_date,is_open\nvendor,2026-10-01,false\nvendor,2026-10-02,true\n"
    import_content = b"calendar_id,cal_date,is_open\nvendor,2026-10-01,true\nvendor,2026-10-02,false\n"
    with TestClient(_calendar_app(session_factory)) as client:
        preview = client.post(
            "/api/v1/market/trading-calendar/csv/preview?calendarId=vendor",
            files={"file": ("preview.csv", preview_content, "text/csv")},
        )
        imported = client.post(
            "/api/v1/market/trading-calendar/csv/import?calendarId=vendor",
            files={"file": ("import.csv", import_content, "text/csv")},
        )
        status = client.get("/api/v1/market/trading-calendar/status?calendarId=vendor")
        diagnostics = client.get(
            "/api/v1/market/trading-calendar/diagnostics",
            params={"calendarId": "vendor", "start": "2026-10-01", "end": "2026-10-02"},
        )

    assert preview.status_code == 200
    assert preview.json() == {
        "start": "2026-10-01",
        "end": "2026-10-02",
        "total": 2,
        "added": 1,
        "changed": 0,
        "unchanged": 1,
    }
    assert imported.json()["changed"] == 1
    assert [row["baseIsOpen"] for row in diagnostics.json()] == [True, False]
    assert all(row["overrideIsOpen"] is None for row in diagnostics.json())
    assert status.json()["refreshKind"] == "csv"
    assert status.json()["functionCode"] == ""
    assert status.json()["overrideCount"] == 0


def test_failed_replacement_rolls_back_base_config_and_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "rollback.db"))
    old_day = date(2026, 1, 1)

    async def exercise() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="vendor", cal_date=old_day, is_open=False))
            session.add(TradingCalendarOverride(calendar_id="vendor", cal_date=old_day, is_open=True))
            session.add(TradingCalendarConfig(calendar_id="vendor", refresh_kind="python", function_code="old-code"))
            await session.commit()
            monkeypatch.setattr(session, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
            entries = [
                calendar_service.CalendarInputEntry(calendar_id="vendor", cal_date=date(2026, 1, 2), is_open=True)
            ]
            with pytest.raises(RuntimeError, match="commit failed"):
                await calendar_service._replace_calendar(
                    session,
                    entries,
                    refresh_kind="python",
                    function_code="new-code",
                )

        async with session_factory() as session:
            base = await session.get(TradingCalendarRecord, ("vendor", old_day))
            override = await session.get(TradingCalendarOverride, ("vendor", old_day))
            config = await session.get(TradingCalendarConfig, "vendor")
            assert base is not None and base.is_open is False
            assert override is not None and override.is_open is True
            assert config is not None and config.function_code == "old-code"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"calendar_id,cal_date,is_open\nchina,2026-01-01,1\n", "true"),
        (
            b"calendar_id,cal_date,is_open\nchina,2026-01-01,true\nchina,2026-01-03,false\n",
            "缺少",
        ),
        (b"calendar_id,cal_date,is_open\nother,2026-01-01,true\n", "china"),
    ],
)
def test_parse_calendar_csv_rejects_invalid_contract(content: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calendar_service.parse_calendar_csv(content)


def test_parse_calendar_csv_supports_multiple_independent_calendar_ids() -> None:
    entries = calendar_service.parse_calendar_csv(
        b"calendar_id,cal_date,is_open\nvendor,2026-01-01,false\nvendor,2026-01-02,true\n",
        calendar_id="vendor",
    )
    assert [(entry.calendar_id, entry.is_open) for entry in entries] == [
        ("vendor", False),
        ("vendor", True),
    ]


def test_save_python_refreshes_immediately_and_clears_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "python-save.db"))
    code = "def get_trading_calendar(calendar_id, start, end): return []"

    async def fake_run(
        _code: str, _start: date, _end: date, *, calendar_id: str
    ) -> calendar_service.CalendarFunctionResult:
        return calendar_service.CalendarFunctionResult(
            valid=True,
            entries=[
                calendar_service.CalendarInputEntry(calendar_id=calendar_id, cal_date=date(2026, 2, 1), is_open=False),
                calendar_service.CalendarInputEntry(calendar_id=calendar_id, cal_date=date(2026, 2, 2), is_open=True),
            ],
        )

    monkeypatch.setattr(calendar_service, "run_calendar_function", fake_run)

    async def exercise() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarOverride(calendar_id="vendor", cal_date=date(2026, 2, 1), is_open=True))
            await session.commit()
            await calendar_service.save_calendar_function(session, calendar_id="vendor", function_code=code)
            config = await session.get(TradingCalendarConfig, "vendor")
            override = await session.get(TradingCalendarOverride, ("vendor", date(2026, 2, 1)))
            base = await session.get(TradingCalendarRecord, ("vendor", date(2026, 2, 1)))
            assert config is not None
            assert config.refresh_kind == "python"
            assert config.function_code == code
            assert override is None
            assert base is not None and base.is_open is False

    asyncio.run(exercise())


def test_python_refresh_is_mutually_exclusive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "concurrent.db"))

    async def exercise() -> tuple[bool, bool]:
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_run(
            _code: str, _start: date, _end: date, *, calendar_id: str
        ) -> calendar_service.CalendarFunctionResult:
            started.set()
            await release.wait()
            return calendar_service.CalendarFunctionResult(
                valid=True,
                entries=[
                    calendar_service.CalendarInputEntry(
                        calendar_id=calendar_id, cal_date=date(2026, 3, 1), is_open=True
                    )
                ],
            )

        monkeypatch.setattr(calendar_service, "SessionLocal", session_factory)
        monkeypatch.setattr(calendar_service, "run_calendar_function", fake_run)
        async with session_factory() as session:
            session.add(TradingCalendarConfig(calendar_id="race", refresh_kind="python", function_code="code"))
            await session.commit()
        first = asyncio.create_task(calendar_service.sync_calendar_python(calendar_id="race", force=True))
        await started.wait()
        second = await calendar_service.sync_calendar_python(calendar_id="race", force=True)
        release.set()
        return await first, second

    assert asyncio.run(exercise()) == (True, False)


def test_failed_python_refresh_preserves_base_config_and_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "refresh-failure.db"))
    calendar_day = date(2026, 3, 1)

    async def fake_run(*_args: object, **_kwargs: object) -> calendar_service.CalendarFunctionResult:
        return calendar_service.CalendarFunctionResult(valid=False, error="source unavailable")

    async def exercise() -> bool:
        monkeypatch.setattr(calendar_service, "SessionLocal", session_factory)
        monkeypatch.setattr(calendar_service, "run_calendar_function", fake_run)
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="vendor", cal_date=calendar_day, is_open=False))
            session.add(TradingCalendarOverride(calendar_id="vendor", cal_date=calendar_day, is_open=True))
            session.add(
                TradingCalendarConfig(
                    calendar_id="vendor",
                    refresh_kind="python",
                    function_code="old-code",
                    last_sync_at="2026-03-01T04:00:00",
                )
            )
            await session.commit()

        refreshed = await calendar_service.sync_calendar_python(calendar_id="vendor", force=True)
        async with session_factory() as session:
            base = await session.get(TradingCalendarRecord, ("vendor", calendar_day))
            override = await session.get(TradingCalendarOverride, ("vendor", calendar_day))
            config = await session.get(TradingCalendarConfig, "vendor")
            assert base is not None and base.is_open is False
            assert override is not None and override.is_open is True
            assert config is not None
            assert config.function_code == "old-code"
            assert config.last_sync_at == "2026-03-01T04:00:00"
        return refreshed

    assert asyncio.run(exercise()) is False


def test_channel_calendar_decisions_and_fail_open_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "decisions.db"))
    open_day = date(2026, 9, 1)
    closed_day = date(2026, 9, 2)
    uncovered_day = date(2026, 9, 3)
    overridden_day = date(2026, 9, 4)

    async def exercise() -> dict[date, calendar_service.CalendarDayDecision]:
        async with session_factory() as session:
            session.add(TradingCalendarConfig(calendar_id="china", refresh_kind="csv"))
            session.add_all(
                [
                    TradingCalendarRecord(calendar_id="china", cal_date=open_day, is_open=True),
                    TradingCalendarRecord(calendar_id="china", cal_date=closed_day, is_open=False),
                    TradingCalendarRecord(calendar_id="china", cal_date=overridden_day, is_open=True),
                    TradingCalendarOverride(calendar_id="china", cal_date=overridden_day, is_open=False),
                ]
            )
            await session.commit()
            return await calendar_service.evaluate_channel_calendar_days(
                session, "ctp", [open_day, closed_day, uncovered_day, overridden_day]
            )

    decisions = asyncio.run(exercise())
    assert decisions[open_day].status is calendar_service.CalendarDecisionStatus.AVAILABLE_OPEN
    assert decisions[closed_day].status is calendar_service.CalendarDecisionStatus.AVAILABLE_CLOSED
    assert decisions[uncovered_day].status is calendar_service.CalendarDecisionStatus.UNAVAILABLE
    assert decisions[uncovered_day].unavailable_reason is calendar_service.CalendarUnavailableReason.UNCOVERED
    assert decisions[overridden_day].status is calendar_service.CalendarDecisionStatus.AVAILABLE_CLOSED
    assert decisions[overridden_day].override_is_open is False

    async def fail_read(*_args: object, **_kwargs: object) -> list[calendar_service.CalendarDiagnosticEntry]:
        raise OSError("database unavailable")

    monkeypatch.setattr(calendar_service, "list_calendar_diagnostics", fail_read)

    async def read_failed() -> calendar_service.CalendarDayDecision:
        async with session_factory() as session:
            return await calendar_service.evaluate_channel_calendar_day(session, "ctp", open_day)

    failed = asyncio.run(read_failed())
    assert failed.status is calendar_service.CalendarDecisionStatus.UNAVAILABLE
    assert failed.unavailable_reason is calendar_service.CalendarUnavailableReason.READ_FAILED


def test_unconfigured_calendar_and_channel_without_calendar_are_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "unavailable.db"))
    day = date(2026, 9, 1)

    async def unconfigured() -> calendar_service.CalendarDayDecision:
        async with session_factory() as session:
            return await calendar_service.evaluate_channel_calendar_day(session, "ctp", day)

    decision = asyncio.run(unconfigured())
    assert decision.status is calendar_service.CalendarDecisionStatus.UNAVAILABLE
    assert decision.unavailable_reason is calendar_service.CalendarUnavailableReason.NOT_CONFIGURED

    plugin = SimpleNamespace(descriptor=SimpleNamespace(calendar=None))
    monkeypatch.setattr(calendar_service, "get_channel", lambda _channel: plugin)
    decision = asyncio.run(unconfigured())
    assert decision.status is calendar_service.CalendarDecisionStatus.NOT_REQUIRED
    assert decision.calendar_id is None


@pytest.mark.parametrize(
    ("triggered_at", "open_days", "expected_day", "expected_status", "expected_reason"),
    [
        (
            "2026-08-24T21:15:00+08:00",
            {date(2026, 8, 24), date(2026, 8, 25)},
            date(2026, 8, 25),
            calendar_service.CalendarDecisionStatus.AVAILABLE_OPEN,
            None,
        ),
        (
            "2026-08-29T01:00:00+08:00",
            {date(2026, 8, 28), date(2026, 8, 31)},
            date(2026, 8, 31),
            calendar_service.CalendarDecisionStatus.AVAILABLE_OPEN,
            None,
        ),
        (
            "2026-08-30T21:15:00+08:00",
            {date(2026, 8, 31)},
            date(2026, 8, 30),
            calendar_service.CalendarDecisionStatus.AVAILABLE_CLOSED,
            "CALENDAR.NO_NIGHT_SESSION",
        ),
        (
            "2026-09-29T21:15:00+08:00",
            {date(2026, 9, 29), date(2026, 10, 1)},
            date(2026, 10, 1),
            calendar_service.CalendarDecisionStatus.AVAILABLE_CLOSED,
            "CALENDAR.NO_NIGHT_SESSION",
        ),
    ],
)
def test_futures_night_trigger_maps_to_trading_day(
    monkeypatch: pytest.MonkeyPatch,
    triggered_at: str,
    open_days: set[date],
    expected_day: date,
    expected_status: calendar_service.CalendarDecisionStatus,
    expected_reason: str | None,
) -> None:
    async def evaluate(
        _session: object,
        channel: object,
        days: list[date],
    ) -> dict[date, calendar_service.CalendarDayDecision]:
        return {
            day: calendar_service.CalendarDayDecision(
                channel=str(channel),
                day=day,
                calendar_id="china",
                label="中国交易日历",
                status=(
                    calendar_service.CalendarDecisionStatus.AVAILABLE_OPEN
                    if day in open_days
                    else calendar_service.CalendarDecisionStatus.AVAILABLE_CLOSED
                ),
                effective_is_open=day in open_days,
            )
            for day in days
        }

    monkeypatch.setattr(calendar_service, "evaluate_channel_calendar_days", evaluate)
    decision = asyncio.run(
        calendar_service.evaluate_channel_calendar_moment(object(), "ctp", datetime.fromisoformat(triggered_at))
    )
    assert decision.day == expected_day
    assert decision.status is expected_status
    assert decision.reason_code == expected_reason


def test_shinny_calendar_materializes_records_using_midnight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Shinny 日历固定以自然日 00:00 判定并写入执行器读取的表。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-save.db"))
    seen: list[datetime] = []

    class FakeCalendarUtility:
        def trading_day(self, value: datetime) -> date:
            seen.append(value)
            return value.date()

    monkeypatch.setattr(calendar_service, "CalendarUtility", FakeCalendarUtility)

    async def exercise() -> None:
        async with session_factory() as session:
            await calendar_service.save_shinny_calendar(
                session,
                calendar_id="china",
                start=date(2026, 8, 20),
                end=date(2026, 8, 21),
            )
            rows = await calendar_service.list_calendar_entries(
                session, calendar_id="china", start=date(2026, 8, 20), end=date(2026, 8, 21)
            )
            config = await session.get(TradingCalendarConfig, "china")
            assert [item.is_open for item in rows] == [True, True]
            assert config is not None and config.refresh_kind == "shinny"

    asyncio.run(exercise())
    assert seen == [datetime(2026, 8, 20), datetime(2026, 8, 21)]


def test_shinny_calendar_does_not_materialize_beyond_2026(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """内置节假日止于 2026，超出范围必须保持未覆盖而非伪造工作日。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-boundary.db"))

    class FakeCalendarUtility:
        def trading_day(self, value: datetime) -> date:
            return value.date()

    monkeypatch.setattr(calendar_service, "CalendarUtility", FakeCalendarUtility)

    async def exercise() -> None:
        async with session_factory() as session:
            await calendar_service.save_shinny_calendar(
                session,
                calendar_id="china",
                start=date(2026, 9, 30),
                end=date(2027, 1, 2),
            )
            entries = await calendar_service.list_calendar_entries(
                session, calendar_id="china", start=date(2026, 9, 30), end=date(2027, 1, 2)
            )
            diagnostics = await calendar_service.list_calendar_diagnostics(
                session, calendar_id="china", start=date(2027, 1, 1), end=date(2027, 1, 2)
            )
            config = await session.get(TradingCalendarConfig, "china")
            assert entries[-1].cal_date == date(2026, 12, 31)
            assert diagnostics == [
                calendar_service.CalendarDiagnosticEntry(calendarId="china", calDate=date(2027, 1, 1)),
                calendar_service.CalendarDiagnosticEntry(calendarId="china", calDate=date(2027, 1, 2)),
            ]
            assert config is not None and config.refresh_kind == "shinny"

    asyncio.run(exercise())


def test_shinny_calendar_service_preserves_calendar_after_supported_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """共享保存入口在 2027 年也必须拒绝，避免旁路路由清空人工调整。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-service-future.db"))
    calendar_day = date(2026, 12, 31)

    class FutureDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2027, 1, 1)

    async def exercise() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="china", cal_date=calendar_day, is_open=False))
            session.add(TradingCalendarOverride(calendar_id="china", cal_date=calendar_day, is_open=True))
            await session.commit()
            with pytest.raises(ValueError, match="2026-12-31"):
                await calendar_service.save_shinny_calendar(
                    session, calendar_id="china", start=calendar_day, end=date(2027, 1, 2)
                )
            record = await session.get(TradingCalendarRecord, ("china", calendar_day))
            override = await session.get(TradingCalendarOverride, ("china", calendar_day))
            assert record is not None and record.is_open is False
            assert override is not None and override.is_open is True

    monkeypatch.setattr(calendar_service, "date", FutureDate)
    asyncio.run(exercise())


def test_shinny_calendar_rejects_non_china_calendar(tmp_path: Path) -> None:
    """Shinny 仅作中国期货和通用节假日兜底。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-calendar-id.db"))

    async def exercise() -> None:
        async with session_factory() as session:
            with pytest.raises(ValueError, match="china"):
                await calendar_service.save_shinny_calendar(
                    session,
                    calendar_id="vendor",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 1),
                )

    asyncio.run(exercise())


def test_shinny_calendar_marks_builtin_holiday_closed(tmp_path: Path) -> None:
    """Shinny 的内置国庆节必须物化为休市。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-holiday.db"))

    async def exercise() -> None:
        async with session_factory() as session:
            await calendar_service.save_shinny_calendar(
                session, calendar_id="china", start=date(2026, 10, 1), end=date(2026, 10, 1)
            )
            entries = await calendar_service.list_calendar_entries(
                session, calendar_id="china", start=date(2026, 10, 1), end=date(2026, 10, 1)
            )
            assert [entry.is_open for entry in entries] == [False]

    asyncio.run(exercise())


def test_shinny_calendar_requires_optional_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少可选依赖时不得把工作日规则静默写入日历。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-dependency.db"))
    monkeypatch.setattr(calendar_service, "CalendarUtility", None)

    async def exercise() -> None:
        async with session_factory() as session:
            with pytest.raises(ValueError, match="axile\\[shinny\\]"):
                await calendar_service.save_shinny_calendar(
                    session, calendar_id="china", start=date(2026, 1, 1), end=date(2026, 1, 1)
                )

    asyncio.run(exercise())


def test_shinny_refresh_skips_covered_year_end_calendar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """年末只检查 Shinny 实际支持的范围，避免重复替换并清空人工调整。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-covered.db"))

    class YearEndDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2026, 12, 18)

    monkeypatch.setattr(calendar_service, "SessionLocal", session_factory)
    monkeypatch.setattr(calendar_service, "date", YearEndDate)
    save = AsyncMock()
    monkeypatch.setattr(calendar_service, "_save_shinny_calendar", save)

    async def exercise() -> bool:
        async with session_factory() as session:
            session.add(TradingCalendarConfig(calendar_id="china", refresh_kind="shinny"))
            session.add_all(
                TradingCalendarRecord(
                    calendar_id="china", cal_date=date(2026, 12, 18) + timedelta(days=offset), is_open=True
                )
                for offset in range(14)
            )
            session.add(TradingCalendarOverride(calendar_id="china", cal_date=date(2026, 12, 18), is_open=False))
            await session.commit()
        refreshed = await calendar_service.sync_calendar_shinny(calendar_id="china")
        async with session_factory() as session:
            override = await session.get(TradingCalendarOverride, ("china", date(2026, 12, 18)))
            assert override is not None and override.is_open is False
        return refreshed

    assert asyncio.run(exercise()) is False
    save.assert_not_awaited()


def test_shinny_refresh_stops_after_supported_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2027 年后自动刷新保留未覆盖状态，不得退化成纯工作日。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-refresh-boundary.db"))

    class FutureDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2027, 1, 1)

    monkeypatch.setattr(calendar_service, "SessionLocal", session_factory)
    monkeypatch.setattr(calendar_service, "date", FutureDate)
    save = AsyncMock()
    monkeypatch.setattr(calendar_service, "_save_shinny_calendar", save)

    async def exercise() -> bool:
        async with session_factory() as session:
            session.add(TradingCalendarConfig(calendar_id="china", refresh_kind="shinny"))
            await session.commit()
        return await calendar_service.sync_calendar_shinny(calendar_id="china", force=True)

    assert asyncio.run(exercise()) is False
    save.assert_not_awaited()


def test_tushare_calendar_maps_all_natural_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tushare 的 trade_cal 返回完整自然日，保存时不需补齐日期。"""
    session_factory = asyncio.run(_create_database(tmp_path / "tushare-save.db"))

    async def fake_fetch(start: date, end: date) -> list[dict[str, str]]:
        assert (start, end) == (date(2026, 1, 1), date(2026, 1, 3))
        return [
            {"cal_date": "20260101", "is_open": "0"},
            {"cal_date": "20260102", "is_open": "1"},
            {"cal_date": "20260103", "is_open": "0"},
        ]

    monkeypatch.setattr(calendar_service, "fetch_tushare_trade_cal", fake_fetch)

    async def exercise() -> None:
        async with session_factory() as session:
            await calendar_service.save_tushare_calendar(
                session,
                calendar_id="ashare",
                start=date(2026, 1, 1),
                end=date(2026, 1, 3),
            )
            rows = await calendar_service.list_calendar_entries(
                session, calendar_id="ashare", start=date(2026, 1, 1), end=date(2026, 1, 3)
            )
            config = await session.get(TradingCalendarConfig, "ashare")
            status = await calendar_service.get_calendar_status(session, "ashare")
            assert [item.is_open for item in rows] == [False, True, False]
            assert config is not None and config.refresh_kind == "tushare"
            assert config.function_code == ""
            assert status.function_code == ""

    asyncio.run(exercise())


def test_tushare_calendar_rejects_non_ashare_calendar(tmp_path: Path) -> None:
    """SSE trade_cal 不得被写入期货共用日历。"""
    session_factory = asyncio.run(_create_database(tmp_path / "tushare-calendar-id.db"))

    async def exercise() -> None:
        async with session_factory() as session:
            with pytest.raises(ValueError, match="ashare"):
                await calendar_service.save_tushare_calendar(
                    session, calendar_id="china", start=date(2026, 1, 1), end=date(2026, 1, 1)
                )

    asyncio.run(exercise())


def test_tushare_refresh_skips_covered_calendar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "tushare-covered.db"))
    today = date.today()

    async def fail_if_called(_start: date, _end: date) -> list[dict[str, str]]:
        raise AssertionError("covered calendar must not fetch")

    monkeypatch.setattr(calendar_service, "SessionLocal", session_factory)
    monkeypatch.setattr(calendar_service, "fetch_tushare_trade_cal", fail_if_called)

    async def exercise() -> bool:
        async with session_factory() as session:
            session.add(TradingCalendarConfig(calendar_id="ashare", refresh_kind="tushare"))
            session.add_all(
                TradingCalendarRecord(calendar_id="ashare", cal_date=today + timedelta(days=offset), is_open=True)
                for offset in range(calendar_service.CALENDAR_MIN_FUTURE_DAYS + 1)
            )
            session.add(TradingCalendarOverride(calendar_id="ashare", cal_date=today, is_open=False))
            await session.commit()
        refreshed = await calendar_service.sync_calendar_tushare(calendar_id="ashare")
        async with session_factory() as session:
            override = await session.get(TradingCalendarOverride, ("ashare", today))
            assert override is not None and override.is_open is False
        return refreshed

    assert asyncio.run(exercise()) is False


def test_shinny_route_rejects_unsupported_calendar(tmp_path: Path) -> None:
    """Shinny 路由不得为不支持的日历写入伪造数据。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-route.db"))

    with TestClient(_calendar_app(session_factory)) as client:
        response = client.put("/api/v1/market/trading-calendar/shinny?calendarId=vendor")

    assert response.status_code == 422
    assert response.json()["detail"] == "Shinny 兜底仅支持 china 日历"


def test_shinny_route_preserves_calendar_after_supported_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2027 年拒绝刷新，不得清除已有基础日历或人工调整。"""
    session_factory = asyncio.run(_create_database(tmp_path / "shinny-route-future.db"))
    calendar_day = date(2026, 12, 31)

    async def seed() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="china", cal_date=calendar_day, is_open=False))
            session.add(TradingCalendarOverride(calendar_id="china", cal_date=calendar_day, is_open=True))
            await session.commit()

    async def verify() -> None:
        async with session_factory() as session:
            record = await session.get(TradingCalendarRecord, ("china", calendar_day))
            override = await session.get(TradingCalendarOverride, ("china", calendar_day))
            assert record is not None and record.is_open is False
            assert override is not None and override.is_open is True

    asyncio.run(seed())
    monkeypatch.setattr("axile.server.api.routes.trading_calendar._today", lambda: date(2027, 1, 1))

    with TestClient(_calendar_app(session_factory)) as client:
        response = client.put("/api/v1/market/trading-calendar/shinny?calendarId=china")

    assert response.status_code == 422
    assert response.json()["detail"] == "Shinny 内置节假日仅覆盖至 2026-12-31"
    asyncio.run(verify())


def test_tushare_route_rejects_futures_calendar(tmp_path: Path) -> None:
    """Tushare 路由不得把 SSE 数据替换到期货日历。"""
    session_factory = asyncio.run(_create_database(tmp_path / "tushare-route-calendar-id.db"))

    with TestClient(_calendar_app(session_factory)) as client:
        response = client.put("/api/v1/market/trading-calendar/tushare?calendarId=china")

    assert response.status_code == 422
    assert response.json()["detail"] == "Tushare 交易日历配置或数据无效"


def test_tushare_route_sanitizes_upstream_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "tushare-route.db"))
    token = "tushare-token-123"

    async def failed_fetch(_start: date, _end: date) -> list[dict[str, str]]:
        raise RuntimeError(f"upstream rejected {token}")

    monkeypatch.setattr(calendar_service, "fetch_tushare_trade_cal", failed_fetch)

    with TestClient(_calendar_app(session_factory)) as client:
        response = client.put("/api/v1/market/trading-calendar/tushare?calendarId=ashare")

    assert response.status_code == 502
    assert response.json()["detail"] == "Tushare 交易日历拉取失败"
    assert token not in response.text


def test_failed_tushare_refresh_preserves_existing_calendar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tushare 不可用时保留已有数据与人工调整。"""
    session_factory = asyncio.run(_create_database(tmp_path / "tushare-failure.db"))
    calendar_day = date(2026, 1, 1)

    async def failed_fetch(_start: date, _end: date) -> list[dict[str, str]]:
        raise ValueError("Tushare trade_cal 不可用")

    monkeypatch.setattr(calendar_service, "fetch_tushare_trade_cal", failed_fetch)

    async def exercise() -> None:
        async with session_factory() as session:
            session.add(TradingCalendarRecord(calendar_id="ashare", cal_date=calendar_day, is_open=False))
            session.add(TradingCalendarOverride(calendar_id="ashare", cal_date=calendar_day, is_open=True))
            session.add(TradingCalendarConfig(calendar_id="ashare", refresh_kind="tushare"))
            await session.commit()
            with pytest.raises(ValueError, match="Tushare trade_cal 不可用"):
                await calendar_service.save_tushare_calendar(
                    session, calendar_id="ashare", start=calendar_day, end=calendar_day
                )
            base = await session.get(TradingCalendarRecord, ("ashare", calendar_day))
            override = await session.get(TradingCalendarOverride, ("ashare", calendar_day))
            config = await session.get(TradingCalendarConfig, "ashare")
            assert base is not None and base.is_open is False
            assert override is not None and override.is_open is True
            assert config is not None and config.refresh_kind == "tushare"

    asyncio.run(exercise())


def test_calendar_function_contract_runs_in_sandbox() -> None:
    code = """
def get_trading_calendar(calendar_id, start, end):
    return [
        {"calendar_id": calendar_id, "cal_date": start.isoformat(), "is_open": True},
        {"calendar_id": calendar_id, "cal_date": end.isoformat(), "is_open": False},
    ]
"""
    result = asyncio.run(calendar_service.run_calendar_function(code, date(2026, 1, 1), date(2026, 1, 2)))
    assert result.valid is True
    assert len(result.entries) == 2


def test_calendar_function_accepts_partial_contiguous_range() -> None:
    code = """
def get_trading_calendar(calendar_id, start, end):
    return [
        {"calendar_id": calendar_id, "cal_date": "2026-01-02", "is_open": True},
        {"calendar_id": calendar_id, "cal_date": "2026-01-03", "is_open": False},
    ]
"""
    result = asyncio.run(calendar_service.run_calendar_function(code, date(2026, 1, 1), date(2026, 1, 4)))

    assert result.valid is True
    assert [entry.cal_date for entry in result.entries] == [date(2026, 1, 2), date(2026, 1, 3)]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "交易日历不能为空"),
        (
            [
                {"calendar_id": "china", "cal_date": "2026-01-01", "is_open": True},
                {"calendar_id": "china", "cal_date": "2026-01-03", "is_open": True},
            ],
            "交易日历区间缺少 1 个自然日",
        ),
        (
            [{"calendar_id": "china", "cal_date": "2026-01-05", "is_open": True}],
            "交易日历日期必须位于 2026-01-01 至 2026-01-04 内",
        ),
    ],
)
def test_calendar_function_rejects_invalid_partial_range(rows: list[dict[str, object]], message: str) -> None:
    code = f"def get_trading_calendar(calendar_id, start, end): return {rows!r}"

    result = asyncio.run(calendar_service.run_calendar_function(code, date(2026, 1, 1), date(2026, 1, 4)))

    assert result.valid is False
    assert result.error == message


class _CalendarHost(AbstractExecutorExecutionRuntimeHostMixin):
    """只承载日历辅助方法的轻量测试宿主。"""


def _calendar_database(path: Path, *, with_day: bool = True) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE trading_calendar (
                calendar_id TEXT, cal_date DATE, is_open BOOLEAN, updated_at TEXT,
                PRIMARY KEY (calendar_id, cal_date)
            );
            CREATE TABLE trading_calendar_override (
                calendar_id TEXT, cal_date DATE, is_open BOOLEAN, updated_at TEXT,
                PRIMARY KEY (calendar_id, cal_date)
            );
            """
        )
        if with_day:
            connection.execute("INSERT INTO trading_calendar VALUES ('china', '2026-10-01', 0, '')")


def test_executor_calendar_only_blocks_explicit_closed_day(tmp_path: Path) -> None:
    path = tmp_path / "reader.db"
    _calendar_database(path)
    host = object.__new__(_CalendarHost)
    host.logger = MagicMock()
    host._trading_calendar = SqliteTradingCalendar(path)

    assert host._is_calendar_open("china", date(2026, 10, 1)) is False
    assert host._is_calendar_open("china", date(2026, 10, 3)) is True


def test_removed_multi_source_routes_are_not_available(tmp_path: Path) -> None:
    session_factory = asyncio.run(_create_database(tmp_path / "removed-routes.db"))
    with TestClient(_calendar_app(session_factory)) as client:
        responses = [
            client.put("/api/v1/market/trading-calendar/enabled", json={"enabled": True}),
            client.put("/api/v1/market/trading-calendar/source", json={"source": "none"}),
            client.delete("/api/v1/market/trading-calendar/sources/csv"),
            client.post("/api/v1/market/trading-calendar/csv/commit/old-preview"),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]


def test_register_calendar_job_is_daily_at_four() -> None:
    scheduler = SimpleNamespace(add_job=MagicMock())
    calendar_service.register_trading_calendar_job(scheduler)  # type: ignore[arg-type]
    scheduler.add_job.assert_called_once_with(
        calendar_service.ensure_trading_calendar_coverage,
        trigger="cron",
        hour=4,
        minute=0,
        id="ensure-trading-calendar",
        replace_existing=True,
    )

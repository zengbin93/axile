"""CTP 品种时段本地快照测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from axile.executor.ctp_product_sessions import CtpProductSession
from axile.executor.ctp_session_snapshot import SqliteCtpSessionSnapshot
from axile.server import ctp_session_snapshot as snapshot_service
from axile.server.db.models import CtpSessionSnapshot, CtpSessionSnapshotRecord

_SHANGHAI = ZoneInfo("Asia/Shanghai")


async def _create_database(path: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _payload() -> dict[str, object]:
    return {
        "rsp_code": 0,
        "rsp_message": "succeed",
        "data": [
            {
                "ExchangeID": "SHFE",
                "ProductID": "ag",
                "SegmentNo": 1,
                "TimeBegin": "21:00:00",
                "TimeEnd": "02:30:00",
                "ProductClass": "1",
                "Area": "China",
            },
            {
                "ExchangeID": "CFFEX",
                "ProductID": "IF",
                "SegmentNo": 1,
                "TimeBegin": "09:30:00",
                "TimeEnd": "11:30:00",
                "ProductClass": "1",
                "Area": "China",
            },
        ],
    }


def test_parse_openctp_payload_rejects_incomplete_or_duplicate_rows() -> None:
    with pytest.raises(ValueError, match="TimeEnd"):
        snapshot_service.parse_openctp_product_sessions(
            {"rsp_code": 0, "data": [{"ExchangeID": "SHFE", "ProductID": "ag", "SegmentNo": 1, "TimeBegin": "21:00:00"}]}
        )
    with pytest.raises(ValueError, match="重复"):
        snapshot_service.parse_openctp_product_sessions(
            {"rsp_code": 0, "data": [_payload()["data"][0], _payload()["data"][0]]}
        )


def test_parse_openctp_payload_only_accepts_successful_futures_response() -> None:
    entries = snapshot_service.parse_openctp_product_sessions(_payload())

    assert [(entry.exchange_id, entry.product_id, entry.segment_no) for entry in entries] == [
        ("CFFEX", "IF", 1),
        ("SHFE", "ag", 1),
    ]
    with pytest.raises(ValueError, match="rsp_code"):
        snapshot_service.parse_openctp_product_sessions({"rsp_code": 1, "data": []})


def test_reader_uses_only_active_complete_snapshot_and_detects_staleness(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    sessions = asyncio.run(_create_database(path))
    now = datetime(2026, 8, 25, 10, 0, tzinfo=_SHANGHAI)

    async def seed() -> None:
        async with sessions() as session:
            session.add_all(
                [
                    CtpSessionSnapshot(snapshot_id="old", fetched_at=(now - timedelta(hours=1)).isoformat(), is_active=False),
                    CtpSessionSnapshot(snapshot_id="active", fetched_at=(now - timedelta(hours=169)).isoformat(), is_active=True),
                    CtpSessionSnapshotRecord(snapshot_id="old", exchange_id="SHFE", product_id="ag", segment_no=1, time_begin="21:00:00", time_end="02:30:00"),
                    CtpSessionSnapshotRecord(snapshot_id="active", exchange_id="SHFE", product_id="ag", segment_no=1, time_begin="21:00:00", time_end="02:30:00"),
                ]
            )
            await session.commit()

    asyncio.run(seed())
    reader = SqliteCtpSessionSnapshot(path)

    result = reader.get_sessions("SHFE", "ag", now=now)

    assert result.reason_code == "CTP.SESSION.SNAPSHOT_STALE"
    assert result.sessions == ()


def test_reader_returns_active_session_rows_and_warns_at_120_hours(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    sessions = asyncio.run(_create_database(path))
    now = datetime(2026, 8, 25, 10, 0, tzinfo=_SHANGHAI)

    async def seed() -> None:
        async with sessions() as session:
            session.add(CtpSessionSnapshot(snapshot_id="active", fetched_at=(now - timedelta(hours=121)).isoformat(), is_active=True))
            session.add(CtpSessionSnapshotRecord(snapshot_id="active", exchange_id="SHFE", product_id="ag", segment_no=1, time_begin="21:00:00", time_end="02:30:00"))
            await session.commit()

    asyncio.run(seed())
    reader = SqliteCtpSessionSnapshot(path)

    result = reader.get_sessions("SHFE", "ag", now=now)

    assert result.reason_code is None
    assert result.warning is True
    assert result.sessions == (CtpProductSession("SHFE", "ag", 1, datetime.strptime("21:00", "%H:%M").time(), datetime.strptime("02:30", "%H:%M").time()),)


def test_replace_activates_new_snapshot_atomically_and_retains_old_on_invalid_data(tmp_path: Path) -> None:
    sessions = asyncio.run(_create_database(tmp_path / "sessions.db"))
    old_entries = snapshot_service.parse_openctp_product_sessions(_payload())

    async def exercise() -> None:
        async with sessions() as session:
            await snapshot_service.replace_ctp_session_snapshot(session, old_entries, fetched_at="2026-08-20T00:00:00+08:00", snapshot_id="old")
            with pytest.raises(ValueError):
                await snapshot_service.replace_ctp_session_snapshot(session, [], fetched_at="2026-08-25T00:00:00+08:00", snapshot_id="bad")
            active = await session.get(CtpSessionSnapshot, "old")
            assert active is not None and active.is_active is True
            await snapshot_service.replace_ctp_session_snapshot(session, old_entries, fetched_at="2026-08-25T00:00:00+08:00", snapshot_id="new")
            await session.refresh(await session.get(CtpSessionSnapshot, "old"))  # type: ignore[arg-type]
            old = await session.get(CtpSessionSnapshot, "old", populate_existing=True)
            new = await session.get(CtpSessionSnapshot, "new", populate_existing=True)
            assert old is not None and old.is_active is False
            assert new is not None and new.is_active is True

    asyncio.run(exercise())


def test_register_snapshot_job_runs_daily_at_four() -> None:
    scheduler = MagicMock()

    snapshot_service.register_ctp_session_snapshot_job(scheduler)  # type: ignore[arg-type]

    scheduler.add_job.assert_called_once_with(
        snapshot_service.ensure_ctp_session_snapshot,
        trigger="cron",
        hour=4,
        minute=10,
        id=snapshot_service.CTP_SESSION_SNAPSHOT_JOB_ID,
        replace_existing=True,
    )


def test_refresh_keeps_active_snapshot_when_http_fetch_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = asyncio.run(_create_database(tmp_path / "sessions.db"))
    monkeypatch.setattr(snapshot_service, "SessionLocal", sessions)
    monkeypatch.setattr(snapshot_service, "fetch_openctp_product_sessions", AsyncMock(side_effect=RuntimeError("offline")))

    assert asyncio.run(snapshot_service.refresh_ctp_session_snapshot()) is False

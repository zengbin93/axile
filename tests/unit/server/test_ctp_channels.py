"""CTP 常驻通道准备任务测试。"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from axile.server.execution import ctp_channels
from tests.unit.server._execution_test_support import build_account


def test_register_ctp_channel_jobs_uses_fixed_session_windows() -> None:
    scheduler = SimpleNamespace(add_job=MagicMock())

    ctp_channels.register_ctp_channel_jobs(scheduler)

    calls = scheduler.add_job.call_args_list
    assert [(call.kwargs["id"], call.kwargs["hour"], call.kwargs["minute"]) for call in calls] == [
        (ctp_channels.CTP_NIGHT_PREPARE_JOB_ID, 20, 30),
        (ctp_channels.CTP_DAY_PREPARE_JOB_ID, 8, 30),
    ]
    assert all(call.kwargs["replace_existing"] is True for call in calls)
    assert all(call.kwargs["max_instances"] == 1 for call in calls)


def test_prepare_ctp_accounts_isolates_account_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    accounts = [build_account(id=1), build_account(id=2)]
    prepared: list[tuple[int | None, str | None]] = []

    class Manager:
        async def prepare_account(self, account: object, expected: str | None = None) -> dict[str, object]:
            account_id = getattr(account, "id")
            prepared.append((account_id, expected))
            if account_id == 1:
                raise RuntimeError("offline")
            return {"trading_day": expected or ""}

    async def expected(_mode: object, _current: object) -> tuple[bool, str | None]:
        return True, "20260824"

    async def started() -> list[object]:
        return accounts

    monkeypatch.setattr(ctp_channels, "_expected_trading_day", expected)
    monkeypatch.setattr(ctp_channels, "_started_ctp_accounts", started)
    monkeypatch.setattr(ctp_channels, "get_worker_backend_manager", Manager)

    asyncio.run(ctp_channels.prepare_ctp_accounts("night", current=date(2026, 8, 22)))

    assert sorted(prepared) == [(1, "20260824"), (2, "20260824")]


def test_prepare_ctp_accounts_skips_closed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    async def expected(_mode: object, _current: object) -> tuple[bool, str | None]:
        return False, None

    started = MagicMock()
    monkeypatch.setattr(ctp_channels, "_expected_trading_day", expected)
    monkeypatch.setattr(ctp_channels, "_started_ctp_accounts", started)

    asyncio.run(ctp_channels.prepare_ctp_accounts("day", current=date(2026, 8, 23)))

    started.assert_not_called()

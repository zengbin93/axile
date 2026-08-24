"""国内常驻通道准备任务测试。"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from axile.server.execution import ctp_channels
from tests.unit.server._execution_test_support import build_account


def test_register_china_channel_jobs_uses_fixed_session_windows() -> None:
    scheduler = SimpleNamespace(add_job=MagicMock())

    ctp_channels.register_china_channel_jobs(scheduler)

    calls = scheduler.add_job.call_args_list
    assert [(call.kwargs["id"], call.kwargs["hour"], call.kwargs["minute"]) for call in calls] == [
        (ctp_channels.CHINA_NIGHT_PREPARE_JOB_ID, 20, 30),
        (ctp_channels.CHINA_DAY_PREPARE_JOB_ID, 8, 30),
    ]
    assert all(call.kwargs["replace_existing"] is True for call in calls)
    assert all(call.kwargs["max_instances"] == 1 for call in calls)


@pytest.mark.parametrize(
    ("current", "next_open", "expected"),
    [
        (date(2026, 8, 20), date(2026, 8, 21), (True, "20260821")),
        (date(2026, 8, 21), date(2026, 8, 24), (True, "20260824")),
        (date(2026, 9, 30), date(2026, 10, 9), (False, None)),
        (date(2026, 10, 9), date(2026, 10, 13), (False, None)),
    ],
)
def test_expected_night_trading_day_only_accepts_regular_transitions(
    monkeypatch: pytest.MonkeyPatch,
    current: date,
    next_open: date,
    expected: tuple[bool, str | None],
) -> None:
    async def entries(*_args: object, **kwargs: object) -> list[object]:
        if kwargs.get("only_open"):
            return [SimpleNamespace(cal_date=next_open, is_open=True)]
        return [SimpleNamespace(cal_date=current, is_open=True)]

    monkeypatch.setattr(ctp_channels, "list_calendar_entries", entries)

    assert asyncio.run(ctp_channels._expected_trading_day("night", current)) == expected


def test_prepare_china_accounts_isolates_account_failures(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(ctp_channels, "_started_china_channel_accounts", started)
    monkeypatch.setattr(ctp_channels, "get_worker_backend_manager", Manager)

    asyncio.run(ctp_channels.prepare_china_channel_accounts("night", current=date(2026, 8, 22)))

    assert sorted(prepared) == [(1, "20260824"), (2, "20260824")]


def test_prepare_china_accounts_skips_closed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    async def expected(_mode: object, _current: object) -> tuple[bool, str | None]:
        return False, None

    started = MagicMock()
    monkeypatch.setattr(ctp_channels, "_expected_trading_day", expected)
    monkeypatch.setattr(ctp_channels, "_started_china_channel_accounts", started)

    asyncio.run(ctp_channels.prepare_china_channel_accounts("day", current=date(2026, 8, 23)))

    started.assert_not_called()


def test_tq_worker_is_rebuilt_before_session_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    account = build_account(id=7, trade_channel="tq", brokerage="tq")
    calls: list[tuple[str, int]] = []

    class Manager:
        async def drop_account(self, account_id: int) -> None:
            calls.append(("drop", account_id))

        async def prepare_account(self, prepared_account: object, expected: str | None = None) -> dict[str, object]:
            del expected
            calls.append(("prepare", int(getattr(prepared_account, "id"))))
            return {"trading_day": ""}

    monkeypatch.setattr(ctp_channels, "get_worker_backend_manager", Manager)

    asyncio.run(ctp_channels._prepare_accounts([account], "night", "20260824"))

    assert calls == [("drop", 7), ("prepare", 7)]

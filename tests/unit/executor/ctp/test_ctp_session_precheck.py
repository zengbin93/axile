"""CTP executor 品种时段预检测试。"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from openctp_ctp import thosttraderapi as td

from axile.executor.ctp.ctp_execute import CTPExecutor

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Calendar:
    def __init__(self, days: dict[date, bool]) -> None:
        self.days = days

    def is_open(self, _calendar_id: str, day: date) -> bool | None:
        return self.days.get(day)


def _executor() -> CTPExecutor:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor._instruments = {
        "ag2612": SimpleNamespace(
            ExchangeID="SHFE",
            ProductID="ag",
            ProductClass=td.THOST_FTDC_PC_Futures,
        ),
        "IF2609": SimpleNamespace(
            ExchangeID="CFFEX",
            ProductID="IF",
            ProductClass=td.THOST_FTDC_PC_Futures,
        ),
        "ag2609C5000": SimpleNamespace(
            ExchangeID="SHFE",
            ProductID="ag",
            ProductClass=td.THOST_FTDC_PC_Options,
        ),
        "unknown2612": SimpleNamespace(ExchangeID="SHFE", ProductID="unknown"),
        "missingclass2612": SimpleNamespace(ExchangeID="SHFE", ProductID="ag"),
    }
    executor._trading_calendar = _Calendar({date(2026, 8, 24): True, date(2026, 8, 25): True})
    return executor


def test_session_check_fails_closed_for_missing_contract_metadata() -> None:
    reason_code = _executor()._get_ctp_session_block_reason("unknown")

    assert reason_code == "CTP.SESSION.NO_METADATA"


def test_session_check_uses_static_contract_exchange_and_product(monkeypatch) -> None:
    monkeypatch.setattr(
        "axile.executor.ctp.ctp_execute.clock_now",
        lambda **_kwargs: datetime(2026, 8, 24, 21, 29, tzinfo=_SHANGHAI),
    )

    assert _executor()._get_ctp_session_block_reason("ag2612") is None


def test_session_check_blocks_unknown_product_and_options_without_session_table() -> None:
    executor = _executor()

    for symbol in ("unknown2612", "ag2609C5000", "missingclass2612"):
        assert executor._get_ctp_session_block_reason(symbol) == "CTP.SESSION.NO_SESSION_TABLE"


def test_session_check_blocks_only_the_structurally_invalid_symbol(monkeypatch) -> None:
    monkeypatch.setattr(
        "axile.executor.ctp.ctp_execute.clock_now",
        lambda **_kwargs: datetime(2026, 8, 24, 21, 29, tzinfo=_SHANGHAI),
    )
    executor = _executor()

    assert executor._get_ctp_session_block_reason("unknown2612") == "CTP.SESSION.NO_SESSION_TABLE"
    assert executor._get_ctp_session_block_reason("ag2612") is None


def test_session_check_fails_closed_for_every_symbol_when_snapshot_expired(monkeypatch) -> None:
    monkeypatch.setattr(
        "axile.executor.ctp.ctp_execute.clock_now",
        lambda **_kwargs: datetime(2027, 8, 25, 21, 29, tzinfo=_SHANGHAI),
    )
    executor = _executor()

    for symbol in ("ag2612", "IF2609"):
        assert executor._get_ctp_session_block_reason(symbol) == "CTP.SESSION.DATA_UNAVAILABLE"

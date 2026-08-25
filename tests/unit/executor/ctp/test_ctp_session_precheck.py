"""CTP executor 品种时段预检测试。"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
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
        "ag2612": SimpleNamespace(ExchangeID="SHFE", ProductID="ag"),
        "IF2609": SimpleNamespace(ExchangeID="CFFEX", ProductID="IF"),
        "ag2609C5000": SimpleNamespace(
            ExchangeID="SHFE",
            ProductID="ag",
            ProductClass=td.THOST_FTDC_PC_Options,
        ),
        "unknown2612": SimpleNamespace(ExchangeID="SHFE", ProductID="unknown"),
    }
    executor._trading_calendar = _Calendar({date(2026, 8, 24): True, date(2026, 8, 25): True})
    return executor


def test_precheck_fails_closed_for_missing_contract_metadata() -> None:
    allowed, reason_code = _executor()._precheck_symbol("unknown")

    assert (allowed, reason_code) == (False, "CTP.SESSION.NO_METADATA")


def test_precheck_uses_static_contract_exchange_and_product(monkeypatch) -> None:
    monkeypatch.setattr(
        "axile.executor.ctp.ctp_execute.clock_now",
        lambda **_kwargs: datetime(2026, 8, 24, 21, 29, tzinfo=_SHANGHAI),
    )

    allowed, reason_code = _executor()._precheck_symbol("ag2612")

    assert (allowed, reason_code) == (True, None)


def test_precheck_blocks_unknown_product_and_options_without_session_table() -> None:
    executor = _executor()

    for symbol in ("unknown2612", "ag2609C5000"):
        allowed, reason_code = executor._precheck_symbol(symbol)
        assert (allowed, reason_code) == (False, "CTP.SESSION.NO_SESSION_TABLE")


def test_ctp_scoped_cancel_only_queries_allowed_dispatch_symbols() -> None:
    executor = _executor()
    pending = SimpleNamespace(symbol="ag2612", order_id="ag-pending")
    executor.get_pending_orders = Mock(side_effect=lambda symbol: [pending] if symbol == "ag2612" else [])
    executor.cancel_order = Mock(return_value=True)

    executor._cancel_orders_before_symbol_dispatch(["ag2612"])

    executor.get_pending_orders.assert_called_once_with("ag2612")
    executor.cancel_order.assert_called_once_with("ag2612", "ag-pending")

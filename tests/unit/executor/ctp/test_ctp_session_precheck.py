"""CTP executor 品种时段预检测试。"""

from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from axile.executor.ctp.ctp_execute import CTPExecutor
from axile.executor.ctp_product_sessions import CtpProductSession
from axile.executor.ctp_session_snapshot import CtpSessionSnapshotResult

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Calendar:
    def __init__(self, days: dict[date, bool]) -> None:
        self.days = days

    def is_open(self, _calendar_id: str, day: date) -> bool | None:
        return self.days.get(day)


class _Snapshot:
    def __init__(self, result: CtpSessionSnapshotResult) -> None:
        self.result = result
        self.requests: list[tuple[str, str]] = []

    def get_sessions(self, exchange_id: str, product_id: str, *, now: datetime | None = None) -> CtpSessionSnapshotResult:
        _ = now
        self.requests.append((exchange_id, product_id))
        return self.result


def _executor() -> CTPExecutor:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor._instruments = {
        "ag2612": SimpleNamespace(ExchangeID="SHFE", ProductID="ag"),
        "IF2609": SimpleNamespace(ExchangeID="CFFEX", ProductID="IF"),
    }
    executor._trading_calendar = _Calendar({date(2026, 8, 24): True, date(2026, 8, 25): True})
    executor.logger = Mock()
    return executor


def test_precheck_fails_closed_for_missing_contract_metadata() -> None:
    executor = _executor()
    executor._ctp_session_snapshot = _Snapshot(CtpSessionSnapshotResult(()))

    allowed, reason_code = executor._precheck_symbol("unknown")

    assert (allowed, reason_code) == (False, "CTP.SESSION.NO_METADATA")


def test_precheck_uses_contract_exchange_and_product_without_network(monkeypatch) -> None:
    executor = _executor()
    snapshot = _Snapshot(
        CtpSessionSnapshotResult(
            (CtpProductSession("SHFE", "ag", 1, time(21), time(2, 30)),),
        )
    )
    executor._ctp_session_snapshot = snapshot
    monkeypatch.setattr("axile.executor.ctp.ctp_execute.clock_now", lambda **_kwargs: datetime(2026, 8, 24, 21, 29, tzinfo=_SHANGHAI))

    allowed, reason_code = executor._precheck_symbol("ag2612")

    assert (allowed, reason_code) == (True, None)
    assert snapshot.requests == [("SHFE", "ag")]


def test_precheck_preserves_snapshot_failure_reason() -> None:
    executor = _executor()
    executor._ctp_session_snapshot = _Snapshot(CtpSessionSnapshotResult((), "CTP.SESSION.SNAPSHOT_STALE"))

    allowed, reason_code = executor._precheck_symbol("ag2612")

    assert (allowed, reason_code) == (False, "CTP.SESSION.SNAPSHOT_STALE")


def test_ctp_scoped_cancel_only_queries_allowed_dispatch_symbols() -> None:
    executor = _executor()
    pending = SimpleNamespace(symbol="ag2612", order_id="ag-pending")
    executor.get_pending_orders = Mock(side_effect=lambda symbol: [pending] if symbol == "ag2612" else [])
    executor.cancel_order = Mock(return_value=True)

    executor._cancel_orders_before_symbol_dispatch(["ag2612"])

    executor.get_pending_orders.assert_called_once_with("ag2612")
    executor.cancel_order.assert_called_once_with("ag2612", "ag-pending")

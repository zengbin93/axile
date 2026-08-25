"""ExecutionRuntime 生命周期与 facade 兼容测试。"""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.models import AccountControlOverride
from axile.executor.account_control.presets import resolve_account_control_policy
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from axile.executor.audit import ExecutionAuditSink
from axile.executor.execution_runtime import ExecutionRuntime, ExecutionRuntimeBindings
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData
from axile.executor.termination import ExecutionTerminationController
from tests.unit.executor._account_control_test_support import normalize_account_control_override


class _Logger:
    def info(self, _message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)

    def warning(self, _message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)

    def error(self, _message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)


def _clock() -> datetime:
    return datetime(2026, 3, 26, 9, 30, 0)


def _build_guard() -> AccountControlGuard:
    return AccountControlGuard(
        account_id=99,
        execution_id="exec-runtime-test",
        channel=TradeChannel.CTP,
        policy=resolve_account_control_policy(
            "default",
            AccountControlOverride.model_validate(normalize_account_control_override({"query_order": {"per_day": 2}})),
        ),
        baseline=AccountControlCounterSnapshot(),
        clock=_clock,
    )


class _AuditSink(ExecutionAuditSink):
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.artifacts: list[dict[str, object]] = []

    def append_event(self, **kwargs: object) -> bool:
        self.events.append(dict(kwargs))
        return True

    def append_artifact(self, **kwargs: object) -> bool:
        self.artifacts.append(dict(kwargs))
        return True


class _RuntimeExecutor(AbstractExecutor):
    def __init__(self) -> None:
        self.logger = _Logger()
        super().__init__(
            TradeChannel.CTP,
            CTPAccountConfig.model_validate(
                {
                    "broker_id": "b",
                    "investor_id": "i",
                    "password": "p",
                    "td_front": "tcp://td:1",
                    "md_front": "tcp://md:2",
                    "app_id": "app",
                    "auth_code": "auth",
                }
            ),
        )

    def _initialize_connection(self, account_config: CTPAccountConfig) -> None:
        self.account_config = account_config

    def _verify_connection(self) -> bool:
        return True

    def _check_trading_time(self) -> bool:
        return True

    def get_account_assets(self) -> UnifiedAccountAssets:
        return UnifiedAccountAssets(
            available_cash=1000.0,
            total_asset=1000.0,
            market_value=0.0,
            positions=[],
        )

    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        return {
            symbol: UnifiedPriceData(
                symbol=symbol,
                last_price=100.0,
                bid_price=99.0,
                ask_price=101.0,
                bid_volume=1.0,
                ask_volume=1.0,
                volume=1.0,
                turnover=1.0,
                timestamp=1,
                update_time="2026-03-26T09:00:00",
            )
            for symbol in symbols
        }

    def _place_order_impl(
        self,
        symbol: str,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0,
        **kwargs: object,
    ) -> UnifiedOrder:
        _ = (direction, order_type, volume, price, kwargs)
        return UnifiedOrder(
            order_id=f"order-{symbol}",
            symbol=symbol,
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=1.0,
            price=100.0,
            status="SUBMITTED",
        )

    def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
        symbol = "rb2610" if symbol is None else symbol
        return [
            UnifiedOrder(
                order_id=f"pending-{symbol}",
                symbol=symbol,
                direction=OrderDirection.BUY,
                order_type=OrderType.LIMIT,
                volume=1.0,
                price=100.0,
                status="PENDING",
            )
        ]

    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        return [
            TradeRecord.create(
                trade_id=f"trade-{order_id}",
                trade_time="2026-03-26T09:00:00",
                trade_volume=1.0,
                trade_price=100.0,
                extra={"symbol": symbol, "order_id": order_id},
            )
        ]

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        _ = (symbol, order_id)
        return True

    def _cleanup(self) -> None:
        return None

    def _get_account_mark(self) -> str:
        return "runtime"

    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, Any]:
        return {symbol: {} for symbol in symbols}

    def register_order_callback(self, callback: object) -> None:
        _ = callback

    def register_price_callback(self, callback: object) -> None:
        _ = callback

    def unregister_order_callback(self, callback: object) -> None:
        _ = callback

    def unregister_price_callback(self, callback: object) -> None:
        _ = callback

    def initialize_websocket(self, symbols: list[str] | None = None) -> None:
        _ = symbols

    def is_monitoring(self) -> bool:
        return False


class _Calendar:
    def __init__(self, open_days: set[date]) -> None:
        self.open_days = open_days

    def is_open(self, _calendar_id: str, day: date) -> bool | None:
        return day in self.open_days


class _UncoveredCalendar:
    def is_open(self, _calendar_id: str, _day: date) -> None:
        return None


def test_china_futures_session_keeps_friday_night_open_after_midnight() -> None:
    executor = _RuntimeExecutor()
    executor.set_channel_calendar("china")
    executor.set_trading_calendar(_Calendar({date(2026, 8, 21), date(2026, 8, 24)}))

    assert executor._is_china_futures_session_open(datetime(2026, 8, 22, 1, 30)) is True
    assert executor._is_china_futures_session_open(datetime(2026, 8, 22, 3, 0)) is False


def test_china_futures_session_rejects_sunday_night_and_holiday_eve() -> None:
    executor = _RuntimeExecutor()
    executor.set_channel_calendar("china")
    executor.set_trading_calendar(
        _Calendar({date(2026, 8, 21), date(2026, 8, 24), date(2026, 9, 30), date(2026, 10, 9)})
    )

    assert executor._is_china_futures_session_open(datetime(2026, 8, 23, 21, 30)) is False
    assert executor._is_china_futures_session_open(datetime(2026, 9, 30, 21, 30)) is False


def test_china_futures_session_allows_uncovered_calendar() -> None:
    """夜盘的未覆盖状态与日盘一致，保留 fail-open 语义。"""
    executor = _RuntimeExecutor()
    executor.set_channel_calendar("china")
    executor.set_trading_calendar(_UncoveredCalendar())

    assert executor._is_china_futures_session_open(datetime(2027, 1, 4, 21, 30)) is True


def test_prepare_execution_runtime_reuses_active_runtime_and_preserves_audit_seq() -> None:
    executor = _RuntimeExecutor()
    executor.set_audit_context({"execution_id": "exec-1", "account_id": 7, "algorithm": "TEST"})

    runtime = executor.prepare_execution_runtime()

    assert executor.prepare_execution_runtime() is runtime
    assert executor.prepare_execution_runtime() is runtime
    assert runtime.audit_context == {"execution_id": "exec-1", "account_id": 7, "algorithm": "TEST"}
    assert executor.next_audit_seq() == 1
    assert executor.next_audit_seq() == 2
    assert runtime.next_audit_seq() == 3


def test_get_active_execution_runtime_only_reads_existing_runtime() -> None:
    """只读接口不应隐式创建 runtime；require 接口才允许创建。"""
    executor = _RuntimeExecutor()

    assert executor.get_active_execution_runtime() is None

    runtime = executor.require_execution_runtime()

    assert executor.get_active_execution_runtime() is runtime

    executor.clear_execution_runtime()

    assert executor.get_active_execution_runtime() is None


def test_runtime_bindings_updates_sync_into_active_runtime() -> None:
    executor = _RuntimeExecutor()
    runtime = executor.prepare_execution_runtime()
    guard = _build_guard()
    audit_sink = _AuditSink()
    controller = ExecutionTerminationController(cancel_event=threading.Event())

    executor.set_audit_context({"execution_id": "exec-2", "account_id": 9, "algorithm": "TEST"})
    executor.set_audit_sink(audit_sink)
    executor.set_account_control_guard(guard)
    executor.set_termination_controller(controller)

    assert runtime.audit_context == {"execution_id": "exec-2", "account_id": 9, "algorithm": "TEST"}
    assert runtime.bindings.audit_sink is audit_sink
    assert runtime.bindings.account_control_guard is guard
    assert runtime.bindings.termination_controller is controller


def test_runtime_can_be_built_from_explicit_bindings() -> None:
    executor = _RuntimeExecutor()
    bindings = ExecutionRuntimeBindings(
        audit_context={"execution_id": "exec-3", "account_id": 3, "algorithm": "TEST"},
        audit_sink=_AuditSink(),
        account_control_guard=_build_guard(),
        termination_controller=ExecutionTerminationController(cancel_event=threading.Event()),
    )

    runtime = ExecutionRuntime(owner=executor, bindings=bindings)

    assert runtime.audit_context["execution_id"] == "exec-3"
    assert runtime.bindings is bindings
    assert runtime.owner is executor


def test_runtime_owns_execution_internal_query_accessors() -> None:
    executor = _RuntimeExecutor()
    runtime = executor.prepare_execution_runtime()
    captured: dict[str, object] = {}

    class _QueryRuntime:
        def get_pending_orders_for_symbol(self, symbol: str) -> list[UnifiedOrder]:
            captured["pending_symbol"] = symbol
            return [
                UnifiedOrder(
                    order_id="pending-runtime",
                    symbol=symbol,
                    direction=OrderDirection.BUY,
                    order_type=OrderType.LIMIT,
                    volume=1.0,
                    price=100.0,
                    status="PENDING",
                )
            ]

        def get_trades_for_order(self, symbol: str, order_id: str) -> list[TradeRecord]:
            captured["trade_query"] = (symbol, order_id)
            return [
                TradeRecord.create(
                    trade_id=f"trade-{order_id}",
                    trade_time="2026-03-26T09:00:00",
                    trade_volume=1.0,
                    trade_price=100.0,
                    extra={"symbol": symbol, "order_id": order_id},
                )
            ]

    runtime._execution_query_runtime = _QueryRuntime()  # type: ignore[assignment]

    orders = runtime.get_pending_orders_for_execution("rb2610")
    trades = runtime.query_trades_for_execution("rb2610", "order-1")

    assert [order.order_id for order in orders] == ["pending-runtime"]
    assert [trade.trade_id for trade in trades] == ["trade-order-1"]
    assert captured == {
        "pending_symbol": "rb2610",
        "trade_query": ("rb2610", "order-1"),
    }


def test_execute_releases_runtime_between_runs(monkeypatch) -> None:
    executor = _RuntimeExecutor()
    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": TradeChannel.CTP.value,
            "account_config": {
                "broker_id": "b",
                "investor_id": "i",
                "password": "p",
                "td_front": "tcp://td:1",
                "md_front": "tcp://md:2",
                "app_id": "app",
                "auth_code": "auth",
            },
            "curr_target": {"rb2610": 0.1},
            "algorithm": {"method": "TEST"},
        }
    )
    observed_runtimes: list[object] = []
    observed_seqs: list[int] = []

    class _FakeEngine:
        def run(self, incoming_input: UnifiedStandardInput) -> UnifiedStandardOutput:
            assert incoming_input is standard_input
            runtime = executor.require_execution_runtime()
            observed_runtimes.append(runtime)
            observed_seqs.append(executor.next_audit_seq())
            return UnifiedStandardOutput(
                account_assets=executor.get_account_assets(),
                inputs=incoming_input,
                status=ExecutionStatus.SUCCEEDED,
                channel_type=executor.channel_type,
                success=True,
            )

    monkeypatch.setattr(executor, "_execution_engine", lambda: _FakeEngine())

    executor.set_audit_context({"execution_id": "exec-1", "account_id": 1, "algorithm": "TEST"})
    executor.execute(standard_input)
    assert executor._active_execution_runtime is None

    executor.set_audit_context({"execution_id": "exec-2", "account_id": 2, "algorithm": "TEST"})
    executor.execute(standard_input)

    assert executor._active_execution_runtime is None
    assert observed_seqs == [1, 1]
    assert observed_runtimes[0] is not observed_runtimes[1]

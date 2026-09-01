"""ExecutionEngine 生命周期 ownership 的测试。"""

from __future__ import annotations

from typing import Any

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.algorithms.core.base import AlgorithmInput
from axile.executor.ctp.ctp_execute import CtpSessionRecoveryRequired
from axile.executor.execution_engine import ExecutionEngine, _PreparedSymbolAlgorithm
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData
from axile.executor.termination import ExecutionTerminated


class _Logger:
    def info(self, _message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)

    def warning(self, _message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)

    def error(self, _message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)


class _LifecycleRecorderExecutor(AbstractExecutor):
    def __init__(self) -> None:
        self.logger = _Logger()
        self.calls: list[str] = []
        self.websocket_init_calls: list[list[str]] = []
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
        self.calls.append("verify_connection")
        return True

    def _ensure_connection(self) -> None:
        self.calls.append("ensure_connection")
        super()._ensure_connection()

    def _reset_execution_state(self, standard_input: UnifiedStandardInput) -> None:
        self.calls.append("reset_execution_state")
        super()._reset_execution_state(standard_input)

    def _check_trading_time(self) -> bool:
        self.calls.append("check_trading_time")
        return True

    def _validate_input(self, standard_input: UnifiedStandardInput) -> None:
        self.calls.append("validate_input")
        super()._validate_input(standard_input)

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
                update_time="2026-03-22T10:00:00",
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

    def _get_pending_orders_impl(self, _symbol: str | None = None) -> list[UnifiedOrder]:
        return []

    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        _ = (symbol, order_id)
        raise NotImplementedError

    def _cleanup(self) -> None:
        self.calls.append("cleanup")

    def _get_account_mark(self) -> str:
        return "lifecycle-test"

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
        self.websocket_init_calls.append(list(symbols or []))

    def is_monitoring(self) -> bool:
        return False

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        _ = (symbol, order_id)
        return True


def _standard_input() -> UnifiedStandardInput:
    return UnifiedStandardInput.from_dict(
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
            "algorithm": {"method": "DEFAULT-ALGO", "params": {"timeout": 3}},
        }
    )


def _output() -> UnifiedStandardOutput:
    return UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(
            available_cash=1000.0,
            total_asset=1000.0,
            market_value=0.0,
            positions=[],
        ),
        memory={},
        inputs=_standard_input(),
        symbol_results={},
        status="NOOP",
        channel_type=TradeChannel.CTP,
        success=True,
    )


def test_base_executor_execute_owns_execution_lifecycle(monkeypatch) -> None:
    """AbstractExecutor.execute 应先完成 execution 生命周期，再进入编排器。"""
    executor = _LifecycleRecorderExecutor()

    class _FakeEngine:
        def run(self, standard_input: UnifiedStandardInput) -> UnifiedStandardOutput:
            assert standard_input.curr_target == {"rb2610": 0.1}
            executor.calls.append("engine_run")
            return _output()

    monkeypatch.setattr(executor, "_execution_engine", lambda: _FakeEngine())

    result = executor.execute(_standard_input())

    assert result.success is True
    assert executor.calls == [
        "ensure_connection",
        "verify_connection",
        "reset_execution_state",
        "check_trading_time",
        "validate_input",
        "engine_run",
        "cleanup",
    ]


def test_execution_engine_run_only_orchestrates_symbol_work(monkeypatch) -> None:
    """ExecutionEngine.run 不应再接管 execution 生命周期。"""
    executor = _LifecycleRecorderExecutor()
    engine = ExecutionEngine(executor)

    def fake_run_symbol_algorithms(standard_input: UnifiedStandardInput) -> list[object]:
        assert standard_input.curr_target == {"rb2610": 0.1}
        executor.calls.append("engine_run_symbol_algorithms")
        return []

    def fake_create_output(standard_input: UnifiedStandardInput, results: list[object]) -> UnifiedStandardOutput:
        assert standard_input.curr_target == {"rb2610": 0.1}
        assert results == []
        executor.calls.append("engine_build_output")
        return _output()

    monkeypatch.setattr(engine, "_run_symbol_algorithms", fake_run_symbol_algorithms)
    monkeypatch.setattr(engine, "_create_standard_output_from_results", fake_create_output)

    result = engine.run(_standard_input())  # type: ignore[attr-defined]

    assert result.success is True
    assert executor.calls == ["engine_run_symbol_algorithms", "engine_build_output"]


def test_execution_engine_prewarms_runtime_before_serial_dispatch(monkeypatch) -> None:
    """串行调度前也应按 stage 一次性预热 runtime。"""
    executor = _LifecycleRecorderExecutor()
    engine = ExecutionEngine(executor)
    tasks = [
        _PreparedSymbolAlgorithm(
            symbol="rb2610",
            algorithm_name="TEST",
            algorithm_input=AlgorithmInput(symbol="rb2610", target_volume=1.0, trade_rule={}),
        ),
        _PreparedSymbolAlgorithm(
            symbol="ag2612",
            algorithm_name="TEST",
            algorithm_input=AlgorithmInput(symbol="ag2612", target_volume=1.0, trade_rule={}),
        ),
    ]
    serial_calls: list[list[str]] = []

    def fake_run_symbol_algorithms_serially(
        prepared_tasks: list[_PreparedSymbolAlgorithm],
    ) -> list[object]:
        serial_calls.append([task.symbol for task in prepared_tasks])
        return []

    monkeypatch.setattr(executor, "_supports_parallel_symbol_dispatch", lambda: False)
    monkeypatch.setattr(engine, "_run_symbol_algorithms_serially", fake_run_symbol_algorithms_serially)

    assert engine._run_prepared_symbol_algorithms(tasks) == []
    assert executor.websocket_init_calls == [["rb2610", "ag2612"]]
    assert serial_calls == [["rb2610", "ag2612"]]


def _prepared_task(symbol: str = "rb2610") -> _PreparedSymbolAlgorithm:
    return _PreparedSymbolAlgorithm(
        symbol=symbol,
        algorithm_name="TEST",
        algorithm_input=AlgorithmInput(symbol=symbol, target_volume=1.0, trade_rule={}),
    )


def test_symbol_error_capture_propagates_termination_instead_of_marking_failed() -> None:
    """协作式终止必须穿透 symbol 级错误捕获，否则会被误报为「执行失败」。"""
    executor = _LifecycleRecorderExecutor()
    engine = ExecutionEngine(executor)

    def terminating_runner() -> object:
        raise ExecutionTerminated(reason="manual stop", mode="cancel_pending")

    with pytest.raises(ExecutionTerminated) as exc_info:
        engine._run_symbol_algorithm_with_error_capture(_prepared_task(), runner=terminating_runner)

    assert exc_info.value.reason == "manual stop"
    assert exc_info.value.mode == "cancel_pending"


def test_symbol_error_capture_propagates_session_recovery() -> None:
    executor = _LifecycleRecorderExecutor()
    engine = ExecutionEngine(executor)

    def recovery_runner() -> object:
        raise CtpSessionRecoveryRequired("ReqQryTradingAccount同步拒绝: return_code=-2", return_code=-2)

    with pytest.raises(CtpSessionRecoveryRequired, match="return_code=-2"):
        engine._run_symbol_algorithm_with_error_capture(_prepared_task(), runner=recovery_runner)


def test_symbol_error_capture_still_converts_generic_error_to_failed_result() -> None:
    """普通异常仍应归一化为该 symbol 的失败结果，不改变既有行为。"""
    executor = _LifecycleRecorderExecutor()
    engine = ExecutionEngine(executor)

    def failing_runner() -> object:
        raise RuntimeError("boom")

    result = engine._run_symbol_algorithm_with_error_capture(_prepared_task("ag2612"), runner=failing_runner)

    assert result.symbol == "ag2612"
    assert result.status == ExecutionStatus.FAILED
    assert "boom" in (result.error or "")

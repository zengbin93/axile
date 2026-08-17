"""`AbstractExecutor.empty_positions()` 流程测试。"""

from __future__ import annotations

from typing import Any

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor import AbstractExecutor
from axile.executor.abstract_executor import facade as abstract_executor_facade_module
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData


class _EmptyPositionsExecutor(AbstractExecutor):
    def __init__(self, account_assets: UnifiedAccountAssets) -> None:
        self._account_assets = account_assets
        super().__init__(TradeChannel.CTP, None)

    def _initialize_connection(self, account_config: object) -> None:
        self.account_config = account_config

    def _verify_connection(self) -> bool:
        return True

    def _check_trading_time(self) -> bool:
        return True

    def get_account_assets(self) -> UnifiedAccountAssets:
        return self._account_assets

    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        _ = symbols
        return {}

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
        _ = symbol
        return []

    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        _ = (symbol, order_id)
        return []

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        _ = (symbol, order_id)
        return True

    def _cleanup(self) -> None:
        return None

    def _get_account_mark(self) -> str:
        return "acct-empty"

    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, object]:
        return {symbol: {"price": "PASSIVE"} for symbol in symbols}

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


def test_empty_positions_returns_noop_result_when_no_positions() -> None:
    executor = _EmptyPositionsExecutor(
        UnifiedAccountAssets(
            available_cash=1000.0,
            total_asset=1000.0,
            market_value=0.0,
            positions=[],
        )
    )
    executor.account_config = CTPAccountConfig.model_validate({"broker_id": "b", "investor_id": "i", "password": "p"})

    result = executor.empty_positions()

    assert result.status == ExecutionStatus.NOOP
    assert result.memory == {"message": "当前账户无持仓，无需清仓"}


def test_empty_positions_executes_and_sends_feishu_notification(monkeypatch) -> None:
    sent: list[tuple[object, object, object]] = []
    captured: dict[str, Any] = {}
    executor = _EmptyPositionsExecutor(
        UnifiedAccountAssets(
            available_cash=900.0,
            total_asset=1000.0,
            market_value=100.0,
            positions=[
                Position(
                    symbol="BTCUSDT",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=100.0,
                )
            ],
        )
    )
    executor.account_config = CTPAccountConfig.model_validate({"broker_id": "b", "investor_id": "i", "password": "p"})

    def fake_execute(
        standard_input: UnifiedStandardInput,
        *,
        cleanup: bool,
        retain_runtime: bool,
    ) -> UnifiedStandardOutput:
        captured["input"] = standard_input
        captured["cleanup"] = cleanup
        captured["retain_runtime"] = retain_runtime
        return UnifiedStandardOutput(
            account_assets=executor.get_account_assets(),
            inputs=standard_input,
            status=ExecutionStatus.SUCCEEDED,
            channel_type=TradeChannel.CTP,
            success=True,
        )

    def fake_sender(source: object, output: object, feishu_key: object) -> None:
        sent.append((source, output, feishu_key))

    monkeypatch.setattr(abstract_executor_facade_module, "send_execute_results_to_feishu", fake_sender)
    monkeypatch.setattr(executor, "execute", fake_execute)
    monkeypatch.setattr(
        executor, "_calculate_last_target_unified", lambda positions: {position.symbol: 0.1 for position in positions}
    )

    result = executor.empty_positions(
        cleanup=False,
        retain_runtime=True,
        feishu_key="hook-empty",
        forbidden_symbols=["ETHUSDT"],
        extra={"source": "test"},
    )

    assert result.success is True
    assert captured["cleanup"] is False
    assert captured["retain_runtime"] is True
    standard_input = captured["input"]
    assert isinstance(standard_input, UnifiedStandardInput)
    assert standard_input.curr_target == {"BTCUSDT": 0.0}
    assert standard_input.last_target == {"BTCUSDT": 0.1}
    assert standard_input.trade_rules == {"BTCUSDT": {"price": "PASSIVE"}}
    assert standard_input.feishu_key == "hook-empty"
    assert standard_input.forbidden_symbols == ["ETHUSDT"]
    assert standard_input.extra["source"] == "test"
    assert sent == [(executor, result, "hook-empty")]


def test_empty_positions_uses_wider_default_timeout(monkeypatch) -> None:
    """清仓未显式指定总超时时，标准输入应带上比调仓更宽的额度。

    清仓是应急去风险：跑久了不如被截断一半糟糕——中途终止会把仓位留在账上，
    而串行下单渠道的总时长约为「品种数 × max_wait_seconds」，用调仓那档额度
    会让稍多品种的清仓稳定半途而废。
    """
    from axile.executor.abstract_executor.facade import DEFAULT_CLEAR_TIMEOUT
    from axile.executor.models.unified_input import DEFAULT_EXECUTION_TIMEOUT_SECONDS

    assert DEFAULT_CLEAR_TIMEOUT > DEFAULT_EXECUTION_TIMEOUT_SECONDS

    captured: dict[str, Any] = {}
    executor = _EmptyPositionsExecutor(
        UnifiedAccountAssets(
            available_cash=900.0,
            total_asset=1000.0,
            market_value=100.0,
            positions=[
                Position(
                    symbol="BTCUSDT",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=100.0,
                )
            ],
        )
    )
    executor.account_config = CTPAccountConfig.model_validate({"broker_id": "b", "investor_id": "i", "password": "p"})

    def fake_execute(standard_input: UnifiedStandardInput, **kwargs: object) -> UnifiedStandardOutput:
        _ = kwargs
        captured["input"] = standard_input
        return UnifiedStandardOutput(
            account_assets=executor.get_account_assets(),
            inputs=standard_input,
            status=ExecutionStatus.SUCCEEDED,
            channel_type=TradeChannel.CTP,
            success=True,
        )

    monkeypatch.setattr(executor, "execute", fake_execute)
    executor.empty_positions()

    assert captured["input"].execution_timeout == DEFAULT_CLEAR_TIMEOUT

    # 调用方显式指定时以调用方为准。
    executor.empty_positions(execution_timeout=90)
    assert captured["input"].execution_timeout == 90

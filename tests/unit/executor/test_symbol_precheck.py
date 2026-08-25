"""ExecutionEngine symbol 预检测试。"""

from __future__ import annotations

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.models.execution_result import AlgorithmResult, ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


class _PrecheckExecutor(AbstractExecutor):
    def __init__(self, decisions: dict[str, tuple[bool, str | None]]) -> None:
        self.decisions = decisions
        self.market_data_requests: list[list[str]] = []
        self.websocket_requests: list[list[str]] = []
        self.cancel_calls = 0
        super().__init__(
            TradeChannel.CTP,
            CTPAccountConfig(
                broker_id="b",
                investor_id="i",
                password="p",
                td_front="tcp://td:1",
                md_front="tcp://md:2",
                app_id="app",
                auth_code="auth",
            ),
        )

    def _initialize_connection(self, account_config: CTPAccountConfig) -> None:
        self.account_config = account_config

    def _verify_connection(self) -> bool:
        return True

    def _check_trading_time(self) -> bool:
        return True

    def _precheck_symbol(self, symbol: str) -> tuple[bool, str | None]:
        return self.decisions[symbol]

    def get_account_assets(self) -> UnifiedAccountAssets:
        return UnifiedAccountAssets(available_cash=1000, total_asset=1000, market_value=0, positions=[])

    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        self.market_data_requests.append(symbols)
        return {
            symbol: UnifiedPriceData(
                symbol=symbol,
                last_price=100,
                bid_price=99,
                ask_price=101,
                bid_volume=1,
                ask_volume=1,
                volume=1,
                turnover=100,
                timestamp=1,
                update_time="2026-08-25T21:29:00",
            )
            for symbol in symbols
        }

    def initialize_websocket(self, symbols: list[str] | None = None) -> None:
        self.websocket_requests.append(list(symbols or []))

    def cancel_all_orders(self) -> None:
        self.cancel_calls += 1

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
            order_id=symbol,
            symbol=symbol,
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=1,
            price=100,
            status="SUBMITTED",
        )

    def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
        _ = symbol
        return []

    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        _ = (symbol, order_id)
        return []

    def _cleanup(self) -> None:
        return None

    def _get_account_mark(self) -> str:
        return "precheck"

    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, dict[str, object]]:
        return {symbol: {} for symbol in symbols}

    def register_order_callback(self, callback: object) -> None:
        _ = callback

    def register_price_callback(self, callback: object) -> None:
        _ = callback

    def unregister_order_callback(self, callback: object) -> None:
        _ = callback

    def unregister_price_callback(self, callback: object) -> None:
        _ = callback

    def is_monitoring(self) -> bool:
        return False

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        _ = (symbol, order_id)
        return True


def _input() -> UnifiedStandardInput:
    return UnifiedStandardInput(
        channel_type=TradeChannel.CTP,
        account_config=CTPAccountConfig(
            broker_id="b",
            investor_id="i",
            password="p",
            td_front="tcp://td:1",
            md_front="tcp://md:2",
            app_id="app",
            auth_code="auth",
        ),
        curr_target={"IF2609": 0.1, "ag2612": 0.2},
        algorithm={"method": "SINGLE-MAKER"},
    )


def test_symbol_precheck_only_queries_and_dispatches_allowed_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    from axile.executor import execution_engine as engine_module

    executor = _PrecheckExecutor({"IF2609": (False, "CTP.SESSION.CLOSED"), "ag2612": (True, None)})
    monkeypatch.setattr(
        engine_module,
        "resolve_algorithm",
        lambda _name, _session: (
            lambda _session, algorithm_input: AlgorithmResult(
                symbol=algorithm_input.symbol, algorithm="SINGLE-MAKER", target_volume=algorithm_input.target_volume
            )
        ),
    )

    output = executor.execute(_input(), cleanup=False)

    assert output.status in {ExecutionStatus.PARTIAL, ExecutionStatus.SUCCEEDED}
    assert output.symbol_results["IF2609"].status == ExecutionStatus.BLOCKED
    assert output.symbol_results["IF2609"].error == "CTP.SESSION.CLOSED"
    assert executor.market_data_requests == [["ag2612"]]
    assert all("IF2609" not in request for request in executor.websocket_requests)


def test_all_symbol_prechecks_block_without_market_data_websocket_or_cancel() -> None:
    executor = _PrecheckExecutor(
        {"IF2609": (False, "CTP.SESSION.CLOSED"), "ag2612": (False, "CTP.SESSION.NO_SESSION_TABLE")}
    )

    output = executor.execute(_input(), cleanup=False)

    assert output.status == ExecutionStatus.BLOCKED
    assert set(output.symbol_results) == {"IF2609", "ag2612"}
    assert executor.market_data_requests == []
    assert executor.websocket_requests == []
    assert executor.cancel_calls == 0

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from axile.executor.algorithms.core.base import AlgorithmInput
from axile.executor.algorithms.defaults.ctp_target_pos_task import impl
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


class _SmartCloseExecutor:
    def __init__(
        self,
        position_extra: dict[str, Any],
        failed_offsets: set[str] | None = None,
        position_extras: list[dict[str, Any]] | None = None,
    ) -> None:
        self.logger = MagicMock()
        self.symbol = "rb2510"
        self.calls: list[dict[str, Any]] = []
        self.failed_offsets = failed_offsets or set()
        self._position_extras = position_extras or [position_extra]
        self._get_assets_calls = 0

    def _build_assets(self, position_extra: dict[str, Any]) -> UnifiedAccountAssets:
        return UnifiedAccountAssets(
            available_cash=1000.0,
            total_asset=1300.0,
            market_value=300.0,
            positions=[
                Position(
                    symbol="rb2510",
                    volume=3.0,
                    available_volume=3.0,
                    market_value=300.0,
                    direction=PositionDirection.LONG,
                    extra=position_extra,
                )
            ],
        )

    def get_account_assets(self) -> UnifiedAccountAssets:
        index = min(self._get_assets_calls, len(self._position_extras) - 1)
        self._get_assets_calls += 1
        return self._build_assets(self._position_extras[index])

    @property
    def _all_orders(self) -> list[UnifiedOrder]:
        return [
            UnifiedOrder(
                order_id=f"order-{idx + 1}",
                symbol=self.symbol,
                direction=call["direction"],
                order_type=call["order_type"],
                volume=call["volume"],
                price=call["price"],
                status="已成交",
                filled_volume=call["volume"],
                avg_price=call["price"],
                extra={"offset_flag": call["offset_flag"]},
            )
            for idx, call in enumerate(self.calls)
        ]

    def get_pending_orders(self) -> list[UnifiedOrder]:
        return self._all_orders

    def query_trades(self, _order_id: str) -> list[TradeRecord]:
        return []

    def is_termination_requested(self) -> bool:
        return False

    def get_termination_mode(self) -> str | None:
        return None

    def handle_termination_checkpoint(self) -> None:
        return None

    def place_order(
        self,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0.0,
        **kwargs: object,
    ) -> UnifiedOrder:
        offset_flag = str(kwargs["offset_flag"])
        self.calls.append(
            {
                "symbol": self.symbol,
                "direction": direction,
                "order_type": order_type,
                "volume": volume,
                "price": price,
                "offset_flag": offset_flag,
            }
        )
        if offset_flag in self.failed_offsets:
            raise RuntimeError(f"submit failed for {offset_flag}")

        return UnifiedOrder(
            order_id=f"order-{len(self.calls)}",
            symbol=self.symbol,
            direction=direction,
            order_type=order_type,
            volume=volume,
            price=price,
            status="待成交",
            filled_volume=0.0,
            avg_price=0.0,
            extra={"offset_flag": offset_flag},
        )

    def get_market_data(self) -> UnifiedPriceData:
        return UnifiedPriceData(
            symbol=self.symbol,
            last_price=3100.0,
            bid_price=3100.0,
            ask_price=3100.0,
            bid_volume=1.0,
            ask_volume=1.0,
            volume=10.0,
            turnover=1000.0,
            timestamp=1,
            update_time="2026-04-01T00:00:00",
        )

    def register_order_callback(self, callback: object) -> None:
        self._registered_order_callback = callback

    def register_price_callback(self, callback: object) -> None:
        self._registered_price_callback = callback

    def unregister_order_callback(self, callback: object) -> None:
        self._unregistered_order_callback = callback

    def unregister_price_callback(self, callback: object) -> None:
        self._unregistered_price_callback = callback

    def cancel_order(self, order_id: str) -> bool:
        if not hasattr(self, "canceled_orders"):
            self.canceled_orders: list[str] = []
        self.canceled_orders.append(order_id)
        return True


def test_smart_close_position_uses_priority_then_generic_fallback() -> None:
    executor = _SmartCloseExecutor(
        position_extra={"long_yd": 2, "long_td": 1},
        failed_offsets={impl.THOST_FTDC_OF_CloseYesterday},
    )
    smart_close_position = getattr(impl, "_smart_close_position")

    orders, executed_volume, success = smart_close_position(
        executor=executor,
        symbol="rb2510",
        direction=OrderDirection.SELL,
        close_volume=3,
        limit_price=4500.0,
        offset_priority="今昨",
    )

    assert [call["offset_flag"] for call in executor.calls] == [
        impl.THOST_FTDC_OF_CloseToday,
        impl.THOST_FTDC_OF_CloseYesterday,
        impl.THOST_FTDC_OF_Close,
    ]
    assert [call["volume"] for call in executor.calls] == [1, 2, 2]
    assert [order.extra["offset_flag"] for order in orders] == [
        impl.THOST_FTDC_OF_CloseToday,
        impl.THOST_FTDC_OF_Close,
    ]
    assert executed_volume == 3
    assert success is True

    info_messages = [call.args[0] for call in executor.logger.info.call_args_list]
    assert any("📋 平仓策略: 先平今再平昨" in message for message in info_messages)
    assert any("🔄 最后尝试通用平仓: 2手" in message for message in info_messages)


def test_execute_position_adjustment_reads_converter_fields_and_generates_close_orders() -> None:
    executor = _SmartCloseExecutor(
        position_extra={
            "long_position": 94,
            "short_position": 0,
            "net_position": 94,
            "long_yd_position": 0,
            "short_yd_position": 0,
            "long_today_position": 94,
            "short_today_position": 0,
        }
    )

    extract_position = getattr(impl, "_extract_ctp_position_details")
    position_detail = extract_position(executor.get_account_assets(), ["rb2510"]).get("rb2510")
    assert position_detail is not None

    execute_adjustment = getattr(impl, "_execute_position_adjustment")
    orders = execute_adjustment(
        executor=executor,
        symbol="rb2510",
        target_volume=0,
        position_detail=position_detail,
        market_data=SimpleNamespace(bid_price=3100.0, ask_price=3100.0),
        price_type="PASSIVE",
        offset_priority="今昨",
    )

    assert len(orders) == 1
    assert orders[0].volume == 94
    assert orders[0].extra["offset_flag"] == impl.THOST_FTDC_OF_CloseToday


def test_extract_ctp_position_details_preserves_totals_for_split_only_fields() -> None:
    executor = _SmartCloseExecutor(
        position_extra={
            "long_yd": 2,
            "long_td": 1,
            "short_yd": 1,
            "short_td": 0,
        }
    )

    extract_position = getattr(impl, "_extract_ctp_position_details")
    position_detail = extract_position(executor.get_account_assets(), ["rb2510"]).get("rb2510")
    assert position_detail is not None

    assert position_detail.long_yesterday == 2
    assert position_detail.long_today == 1
    assert position_detail.long_total == 3
    assert position_detail.short_yesterday == 1
    assert position_detail.short_today == 0
    assert position_detail.short_total == 1
    assert position_detail.net_position == 2


def test_ctp_target_pos_task_algorithm_reports_failed_when_target_not_reached() -> None:
    executor = _SmartCloseExecutor(
        position_extra={
            "long_position": 2,
            "short_position": 0,
            "net_position": 2,
            "long_yd_position": 1,
            "short_yd_position": 0,
            "long_today_position": 1,
            "short_today_position": 0,
        }
    )
    algorithm_input = AlgorithmInput(
        symbol="rb2510",
        target_volume=0,
        trade_rule={"price": "PASSIVE", "offset_priority": "今昨"},
        params=impl.CTPTargetPosTaskParams(max_wait_seconds=1),
    )

    result = impl.ctp_target_pos_task_algorithm(executor, algorithm_input)

    assert result.status == ExecutionStatus.FAILED
    assert result.error == "rb2510 持仓调整失败: 当前净持仓 2，目标 0"
    result_memory = result.memory
    assert result_memory["target_reached"] is False
    assert result_memory["current_net_position"] == 2
    assert result_memory["final_net_position"] == 2

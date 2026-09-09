from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.capability import AbstractExecutorCapabilityMixin
from axile.executor.algorithms.core.base import AlgorithmInput, ExecutorProtocol
from axile.executor.algorithms.defaults.ctp_target_pos_task.impl import (
    CTPTargetPosTaskParams,
    _calculate_order_price,
    _extract_ctp_position_details,
    ctp_target_pos_task_algorithm,
)
from axile.executor.constants.order_status import OrderStatus
from axile.executor.ctp.converters import account_to_unified
from axile.executor.ctp.ctp_execute import CtpSessionRecoveryRequired
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


def _native_book(reverse_rows=False, reverse_positions=False, split=False):
    rows = []
    for direction, total, today in (("2", 5, 2), ("3", 3, 1)):
        quantities = [(today, today), (total - today, 0)] if split else [(total, today)]
        for volume, td_volume in quantities:
            rows.append(
                {
                    "InstrumentID": "rb2610",
                    "PosiDirection": direction,
                    "Position": volume,
                    "TodayPosition": td_volume,
                    "YdPosition": total + 4,
                }
            )
    if reverse_rows:
        rows.reverse()
    book = account_to_unified({}, rows, {})
    if reverse_positions:
        book.positions.reverse()
    return book


@pytest.mark.parametrize("reverse_rows", [False, True])
@pytest.mark.parametrize("reverse_positions", [False, True])
@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("target", [2, 4])
def test_production_positions_aggregate_and_reach_target(reverse_rows, reverse_positions, split, target):
    book = _native_book(reverse_rows, reverse_positions, split)
    detail = _extract_ctp_position_details(book, ["rb2610"])["rb2610"]
    assert (detail.long_total, detail.short_total, detail.net_position) == (5, 3, 2)
    assert detail.net_position == AbstractExecutorCapabilityMixin().get_current_volume("rb2610", book)
    assert (detail.long_today, detail.long_yesterday, detail.short_today, detail.short_yesterday) == (2, 3, 1, 2)
    executor = _FuturesExecutor(TradeChannel.CTP)
    executor.get_account_assets = lambda: book
    result = ctp_target_pos_task_algorithm(
        cast("ExecutorProtocol", executor),
        AlgorithmInput(
            symbol="rb2610",
            target_volume=target,
            trade_rule={},
            params=CTPTargetPosTaskParams(max_wait_seconds=1),
        ),
    )
    assert result.status == (ExecutionStatus.SUCCEEDED if target == 2 else ExecutionStatus.FAILED)
    assert result.memory["current_net_position"] == result.memory["final_net_position"] == 2
    assert result.memory["execution_details"]["rb2610_adjustment"]["current_net"] == 2
    assert [(order.direction, order.volume, order.extra["offset_flag"]) for order in executor.orders] == (
        [] if target == 2 else [(OrderDirection.BUY, 2, "4")]
    )


def test_final_check_does_not_accept_first_direction_as_net():
    book = _native_book()
    executor = _FuturesExecutor(TradeChannel.CTP)
    executor.get_account_assets = lambda: book
    result = ctp_target_pos_task_algorithm(
        cast("ExecutorProtocol", executor),
        AlgorithmInput(
            symbol="rb2610",
            target_volume=5,
            trade_rule={},
            params=CTPTargetPosTaskParams(max_wait_seconds=1),
        ),
    )
    assert result.status == ExecutionStatus.FAILED
    assert result.memory["final_net_position"] == 2
    assert result.memory["target_reached"] is False


@pytest.mark.parametrize("indices,expected", [([], (0, 0, 0)), ([0], (5, 0, 5)), ([1], (0, 3, -3))])
def test_position_aggregation_boundaries(indices, expected):
    book = _native_book()
    selected = [book.positions[index] for index in indices]
    selected.append(book.positions[0].model_copy(update={"symbol": "other"}))
    book.positions = selected
    detail = _extract_ctp_position_details(book, ["rb2610"])["rb2610"]
    assert (detail.long_total, detail.short_total, detail.net_position) == expected


@pytest.mark.parametrize(
    "extra",
    [
        {"long_td": 6, "long_yd": 0},
        {"long_td": 2, "long_yd": 2},
        {"long_td": -1, "long_yd": 6},
        {"long_td": 2.5, "long_yd": 2.5},
        {"long_td": 2, "long_yd": 3, "long_total": 8},
        {},
    ],
)
def test_inconsistent_position_blocks_orders(extra):
    book = _native_book()
    book.positions[0].extra = extra
    executor = _FuturesExecutor(TradeChannel.CTP)
    executor.get_account_assets = lambda: book
    result = ctp_target_pos_task_algorithm(
        cast("ExecutorProtocol", executor),
        AlgorithmInput(
            symbol="rb2610",
            target_volume=8,
            trade_rule={},
            params=CTPTargetPosTaskParams(max_wait_seconds=1),
        ),
    )
    assert result.status == ExecutionStatus.FAILED
    assert result.error
    assert executor.orders == []


def test_converter_rejects_today_exceeding_total():
    with pytest.raises(ValueError, match="今仓与总持仓不一致"):
        account_to_unified(
            {}, [{"InstrumentID": "rb2610", "PosiDirection": "2", "Position": 1, "TodayPosition": 2}], {}
        )


@pytest.mark.parametrize("field", ["Position", "TodayPosition"])
@pytest.mark.parametrize("value", [-1, 0.5, float("nan"), float("inf"), "bad", None, True])
def test_converter_rejects_invalid_position_quantity(field, value):
    row = {"InstrumentID": "rb2610", "PosiDirection": "2", "Position": 5, "TodayPosition": 2}
    row[field] = value
    with pytest.raises(ValueError, match="持仓数量必须是非负整数"):
        account_to_unified({}, [row], {})


class _FuturesExecutor:
    def __init__(self, channel_type: TradeChannel) -> None:
        self.channel_type = channel_type
        self.symbol = "rb2610"
        self.logger = MagicMock()
        self.long_today = 0
        self.long_yesterday = 0
        self.short_today = 1
        self.short_yesterday = 1
        self.order_callbacks: list[object] = []
        self.price_callbacks: list[object] = []
        self.trade_callbacks: list[object] = []
        self.orders: list[UnifiedOrder] = []

    def _position(self, direction: PositionDirection, today: int, yesterday: int) -> Position:
        side = "long" if direction == PositionDirection.LONG else "short"
        return Position(
            symbol=self.symbol,
            volume=today + yesterday,
            available_volume=today + yesterday,
            market_value=(today + yesterday) * 3200 * 10,
            direction=direction,
            avg_price=3200,
            extra={
                f"{side}_td": today,
                f"{side}_yd": yesterday,
            },
        )

    def get_account_assets(self) -> UnifiedAccountAssets:
        positions = []
        if self.long_today + self.long_yesterday:
            positions.append(self._position(PositionDirection.LONG, self.long_today, self.long_yesterday))
        if self.short_today + self.short_yesterday:
            positions.append(self._position(PositionDirection.SHORT, self.short_today, self.short_yesterday))
        return UnifiedAccountAssets(
            available_cash=1_000_000,
            total_asset=1_000_000,
            market_value=sum(position.market_value for position in positions),
            positions=positions,
        )

    def get_market_data(self) -> UnifiedPriceData:
        return UnifiedPriceData(
            symbol=self.symbol,
            last_price=3200,
            bid_price=3199,
            ask_price=3201,
            bid_volume=10,
            ask_volume=10,
            volume=100,
            turnover=3_200_000,
            timestamp=1,
            update_time="2026-08-23T09:00:00",
        )

    def place_order(
        self,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0,
        **kwargs: object,
    ) -> UnifiedOrder:
        lots = int(volume)
        offset = str(kwargs.get("offset_flag", "0"))
        if offset == "4":
            self.short_yesterday -= lots
        elif offset == "3":
            self.short_today -= lots
        elif offset == "0" and direction is OrderDirection.BUY:
            self.long_today += lots
        order = UnifiedOrder(
            order_id=f"{self.channel_type}-{len(self.orders) + 1}",
            symbol=self.symbol,
            direction=direction,
            order_type=order_type,
            volume=volume,
            price=price,
            status=OrderStatus.FILLED,
            filled_volume=volume,
            avg_price=price,
            extra={"offset_flag": offset},
        )
        self.orders.append(order)
        for callback in tuple(self.order_callbacks):
            callback(order)  # type: ignore[operator]
        trade = TradeRecord(
            trade_id=f"{order.order_id}-t1",
            symbol=self.symbol,
            order_id=order.order_id,
            trade_time="2026-08-23T09:00:00",
            trade_volume=float(volume),
            trade_price=float(price),
            trade_value=float(volume) * float(price),
        )
        for callback in tuple(self.trade_callbacks):
            callback(trade)  # type: ignore[operator]
        return order

    def register_order_callback(self, callback: object) -> None:
        self.order_callbacks.append(callback)

    def unregister_order_callback(self, callback: object) -> None:
        self.order_callbacks.remove(callback)

    def register_price_callback(self, callback: object) -> None:
        self.price_callbacks.append(callback)

    def unregister_price_callback(self, callback: object) -> None:
        self.price_callbacks.remove(callback)

    def register_trade_callback(self, callback: object) -> None:
        self.trade_callbacks.append(callback)

    def unregister_trade_callback(self, callback: object) -> None:
        self.trade_callbacks.remove(callback)

    def get_pending_orders(self) -> list[UnifiedOrder]:
        return []

    def query_trades(self, _order_id: str) -> list[object]:
        return []

    def cancel_order(self, _order_id: str) -> bool:
        return True

    def is_termination_requested(self) -> bool:
        return False

    def get_termination_mode(self) -> str | None:
        return None

    def handle_termination_checkpoint(self) -> None:
        return None


@pytest.mark.parametrize("channel", [TradeChannel.CTP, TradeChannel.TQ])
def test_target_pos_task_uses_same_close_then_open_flow(channel: TradeChannel) -> None:
    executor = _FuturesExecutor(channel)
    algorithm_input = AlgorithmInput(
        symbol="rb2610",
        target_volume=1,
        trade_rule={"price": "PASSIVE", "offset_priority": "昨今"},
        params=CTPTargetPosTaskParams(max_wait_seconds=1),
    )

    result = ctp_target_pos_task_algorithm(cast("ExecutorProtocol", executor), algorithm_input)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.memory["target_reached"] is True
    assert [order.extra["offset_flag"] for order in executor.orders] == ["4", "3", "0"]
    assert executor.short_yesterday == executor.short_today == 0
    assert executor.long_today == 1
    assert executor.order_callbacks == []
    assert executor.trade_callbacks == []
    assert len(result.trades) == len(executor.orders) == 3
    assert result.memory["trades_generated"] == 3
    assert [trade.order_id for trade in result.trades] == [order.order_id for order in executor.orders]


def test_target_pos_task_params_expose_execution_defaults() -> None:
    params = CTPTargetPosTaskParams()

    assert params.model_dump() == {
        "chase_enabled": False,
        "chase_ticks": 1,
        "max_chase_count": 5,
        "chase_interval": 5.0,
        "max_wait_seconds": 60,
        "price_strategy": "PASSIVE",
        "offset_priority": "昨今",
    }


@pytest.mark.parametrize(
    ("price_strategy", "direction", "expected"),
    [
        ("PASSIVE", OrderDirection.BUY, 3199),
        ("PASSIVE", OrderDirection.SELL, 3201),
        ("ACTIVE", OrderDirection.BUY, 3201),
        ("ACTIVE", OrderDirection.SELL, 3199),
    ],
)
def test_target_pos_task_price_strategy_uses_expected_book_side(
    price_strategy: str,
    direction: OrderDirection,
    expected: float,
) -> None:
    market_data = _FuturesExecutor(TradeChannel.CTP).get_market_data()

    assert _calculate_order_price(market_data, price_strategy, direction) == expected


def test_target_pos_task_active_price_falls_back_to_last_price() -> None:
    market_data = _FuturesExecutor(TradeChannel.CTP).get_market_data().model_copy(update={"ask_price": 0})

    assert _calculate_order_price(market_data, "ACTIVE", OrderDirection.BUY) == 3200


@pytest.mark.parametrize("channel", [TradeChannel.CTP, TradeChannel.TQ])
def test_target_pos_task_uses_params_when_trade_rule_has_no_override(channel: TradeChannel) -> None:
    executor = _FuturesExecutor(channel)
    algorithm_input = AlgorithmInput(
        symbol="rb2610",
        target_volume=1,
        trade_rule={},
        params=CTPTargetPosTaskParams(
            max_wait_seconds=1,
            price_strategy="ACTIVE",
            offset_priority="今昨",
        ),
    )

    result = ctp_target_pos_task_algorithm(cast("ExecutorProtocol", executor), algorithm_input)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert [order.extra["offset_flag"] for order in executor.orders] == ["3", "4", "0"]
    assert [order.price for order in executor.orders] == [3201, 3201, 3201]


def test_target_pos_task_trade_rule_overrides_algorithm_params() -> None:
    executor = _FuturesExecutor(TradeChannel.CTP)
    algorithm_input = AlgorithmInput(
        symbol="rb2610",
        target_volume=1,
        trade_rule={"price": "PASSIVE", "offset_priority": "昨今"},
        params=CTPTargetPosTaskParams(
            max_wait_seconds=1,
            price_strategy="ACTIVE",
            offset_priority="今昨",
        ),
    )

    result = ctp_target_pos_task_algorithm(cast("ExecutorProtocol", executor), algorithm_input)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert [order.extra["offset_flag"] for order in executor.orders] == ["4", "3", "0"]
    assert [order.price for order in executor.orders] == [3199, 3199, 3199]


def test_target_pos_task_propagates_session_recovery_from_final_account_query() -> None:
    class _RecoveryExecutor(_FuturesExecutor):
        def __init__(self) -> None:
            super().__init__(TradeChannel.CTP)
            self.account_asset_calls = 0

        def get_account_assets(self) -> UnifiedAccountAssets:
            self.account_asset_calls += 1
            if self.account_asset_calls == 2:
                raise CtpSessionRecoveryRequired("ReqQryTradingAccount同步拒绝: return_code=-2", return_code=-2)
            return super().get_account_assets()

    executor = _RecoveryExecutor()
    algorithm_input = AlgorithmInput(
        symbol="rb2610",
        target_volume=-2,
        trade_rule={},
        params=CTPTargetPosTaskParams(max_wait_seconds=1),
    )

    with pytest.raises(CtpSessionRecoveryRequired, match="return_code=-2"):
        ctp_target_pos_task_algorithm(cast("ExecutorProtocol", executor), algorithm_input)

    assert executor.account_asset_calls == 2

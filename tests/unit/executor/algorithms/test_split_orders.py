"""穿零拆单 helper(submit_and_track_split_orders)回归测试."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from axile.common.order_param_model import OrderParamModel
from axile.executor.algorithms.utils.order_helper import (
    determine_close_intent,
    submit_and_track_split_orders,
)
from axile.executor.models.unified_account_assets import PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder


class _FakeTracker:
    """最小订单跟踪器替身:登记订单并记录等待次数."""

    def __init__(self) -> None:
        self.orders: list[tuple[UnifiedOrder, dict[str, Any]]] = []
        self.wait_calls = 0

    def add_order(self, order: UnifiedOrder, **kwargs: Any) -> None:
        self.orders.append((order, kwargs))

    def wait_for_completion(self, timeout: float | None = None) -> None:
        _ = timeout
        self.wait_calls += 1


def _make_executor(model: OrderParamModel) -> MagicMock:
    executor = MagicMock()
    executor.symbol = "rb2610"
    executor.order_param_model = model
    executor.get_min_notional.return_value = None
    counter = [0]

    def place_order(direction, order_type, volume, price=0, **kwargs):
        counter[0] += 1
        return UnifiedOrder(
            order_id=f"o{counter[0]}",
            symbol="rb2610",
            direction=direction,
            order_type=order_type,
            volume=volume,
            price=price,
            status="待成交",
            filled_volume=0.0,
            avg_price=0.0,
            extra=dict(kwargs),
        )

    executor.place_order.side_effect = place_order
    return executor


_ASSETS = UnifiedAccountAssets(available_cash=0.0, total_asset=0.0, market_value=0.0, positions=[])


def _submit(executor, tracker, direction, volume, target, current, price=100.0):
    return submit_and_track_split_orders(
        executor,
        tracker,
        direction,
        OrderType.LIMIT,
        volume,
        price,
        target_volume=float(target),
        current_volume=float(current),
        account_assets=_ASSETS,
        leg_timeout_seconds=1.0,
    )


def test_passthrough_single_order_on_position_side_model() -> None:
    """POSITION_SIDE 模型:单笔直通,不查持仓."""
    executor = _make_executor(OrderParamModel.POSITION_SIDE)
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.BUY, 5, target=5, current=0)

    assert len(orders) == 1
    assert executor.place_order.call_count == 1
    executor.get_positions.assert_not_called()
    assert tracker.wait_calls == 0


def test_unknown_model_fails_loud() -> None:
    """UNKNOWN 模型:歧义即失败,拒绝猜测下单语义."""
    executor = _make_executor(OrderParamModel.UNKNOWN)
    tracker = _FakeTracker()

    with pytest.raises(RuntimeError, match="拒绝猜测下单语义"):
        _submit(executor, tracker, OrderDirection.BUY, 5, target=5, current=0)

    executor.place_order.assert_not_called()


def test_offset_model_pure_open_without_position() -> None:
    """OFFSET 模型:无反向持仓时单笔开仓,不带 position_side."""
    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.return_value = []
    executor.get_current_volume.return_value = -5.0
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.SELL, 5, target=-5, current=0)

    assert len(orders) == 1
    _, kwargs = executor.place_order.call_args
    assert "position_side" not in kwargs


def test_offset_model_exact_close_single_leg() -> None:
    """OFFSET 模型:下单量恰等于反向持仓,单笔平仓."""
    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.return_value = [(2.0, PositionDirection.LONG)]
    executor.get_current_volume.return_value = 0.0
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.SELL, 2, target=0, current=2)

    assert len(orders) == 1
    assert executor.place_order.call_args.args[2] == 2
    assert executor.place_order.call_args.kwargs["position_side"] == "LONG"


def test_offset_model_cross_zero_splits_close_then_open() -> None:
    """OFFSET 模型:穿零拆成先平后开两腿,逐腿门控."""
    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.side_effect = [[(2.0, PositionDirection.LONG)], []]
    executor.get_current_volume.side_effect = [0.0, -3.0]
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.SELL, 5, target=-3, current=2)

    assert [call.args[2] for call in executor.place_order.call_args_list] == [2, 3]
    assert executor.place_order.call_args_list[0].kwargs["position_side"] == "LONG"
    assert "position_side" not in executor.place_order.call_args_list[1].kwargs
    assert tracker.wait_calls == 2
    assert len(orders) == 2


def test_offset_model_partial_fill_self_heals() -> None:
    """OFFSET 模型:平仓腿部分成交后,按复核持仓继续补平再开仓."""
    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.side_effect = [[(2.0, PositionDirection.LONG)], [(1.0, PositionDirection.LONG)], []]
    executor.get_current_volume.side_effect = [1.0, 0.0, -3.0]
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.SELL, 5, target=-3, current=2)

    volumes = [call.args[2] for call in executor.place_order.call_args_list]
    assert volumes == [2, 1, 3]
    sides = ["position_side" in call.kwargs for call in executor.place_order.call_args_list]
    assert sides == [True, True, False]
    assert len(orders) == 3


def test_offset_model_close_leg_skipped_blocks_open_leg() -> None:
    """OFFSET 模型:平仓腿不可执行时绝不补开仓腿(防锁仓门)."""
    from axile.executor.algorithms.exceptions import SubMinQuantityError

    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.return_value = [(2.0, PositionDirection.LONG)]
    executor.place_order.side_effect = SubMinQuantityError("碎量")
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.SELL, 5, target=-3, current=2)

    assert orders == []
    assert executor.place_order.call_count == 1
    assert tracker.wait_calls == 0


def test_offset_model_open_leg_chunked_by_volume_bounds() -> None:
    """OFFSET 模型:开仓腿超单笔上限时按上限分段."""
    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.return_value = []
    executor.get_current_volume.return_value = -5.0
    executor.get_order_volume_bounds.return_value = (1, 2)
    tracker = _FakeTracker()

    orders = _submit(executor, tracker, OrderDirection.SELL, 5, target=-5, current=0)

    assert [call.args[2] for call in executor.place_order.call_args_list] == [2, 2, 1]
    assert len(orders) == 3


def test_determine_close_intent_reports_opposite_volume() -> None:
    """determine_close_intent 返回可平反向持仓量供拆单使用."""
    executor = _make_executor(OrderParamModel.OFFSET)
    executor.get_positions.return_value = [(2.0, PositionDirection.LONG), (1.0, PositionDirection.SHORT)]

    intent = determine_close_intent(executor, OrderDirection.SELL, _ASSETS)

    assert intent.kwargs == {"position_side": "LONG"}
    assert intent.opposite_volume == 2.0

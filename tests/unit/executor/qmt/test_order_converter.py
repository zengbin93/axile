"""QMT 订单状态转换器测试。"""

from __future__ import annotations

from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.utils.order_tracker import OrderTracker
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder
from tests.unit.executor._qmt_test_support import install_qmt_stubs

install_qmt_stubs()

from axile.executor.qmt.converters.order_converter import (  # noqa: E402
    convert_qmt_order_status_to_string,
)


class _Logger:
    def debug(self, *_args: object, **_kwargs: object) -> None:
        pass

    def info(self, *_args: object, **_kwargs: object) -> None:
        pass

    def warning(self, *_args: object, **_kwargs: object) -> None:
        pass

    def error(self, *_args: object, **_kwargs: object) -> None:
        pass


class _FakeExecutor:
    channel_type = TradeChannel.QMT
    symbol = "600000.SH"

    def __init__(self) -> None:
        self.logger = _Logger()


def _build_pending_order(order_id: str) -> UnifiedOrder:
    return UnifiedOrder.create(
        order_id=order_id,
        symbol="600000.SH",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=100,
        price=12.3,
        status=OrderStatus.SUBMITTED,
        channel_type=TradeChannel.QMT,
    )


def test_qmt_order_status_57_maps_to_rejected() -> None:
    """QMT 废单（order_status=57）应映射为统一终态 REJECTED，而不是裸字符串。"""
    status = convert_qmt_order_status_to_string(57)

    assert status == OrderStatus.REJECTED
    assert OrderStatus.is_completed(status)


def test_qmt_rejected_order_converges_from_pending_to_completed() -> None:
    """废单状态应能驱动 OrderTracker 把订单从 pending 收敛到 completed。"""
    tracker = OrderTracker(executor=_FakeExecutor())
    order = _build_pending_order("qmt-rejected-1")
    tracker.add_order(order, direction=OrderDirection.BUY)
    assert "qmt-rejected-1" in tracker.pending_orders

    rejected_status = convert_qmt_order_status_to_string(57)
    rejected_order = order.model_copy(update={"status": rejected_status})
    tracker.on_order_update(rejected_order)

    assert "qmt-rejected-1" not in tracker.pending_orders
    assert "qmt-rejected-1" in tracker.completed_orders
    assert tracker.all_done_event.is_set()

"""``ExecutionSession`` 对渠道特有能力的条件代理测试.

验证 WS 丢帧兜底 ``reconcile_terminal_order`` 在渠道代理路径保持可用
已修复：能力经真实 ``ExecutionSession``（而非绕过它的强替身）代理到 owner；owner 不具备
时安全降级，保持 CTP / GM 等渠道行为不变。
"""

from __future__ import annotations

from typing import Any, cast

from axile.common.trade_channel import TradeChannel
from axile.executor.execution_session import ExecutionSession
from axile.executor.models.order_channel_health import OrderChannelHealth
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder


class _Logger:
    def debug(self, message: object, *args: object, **kwargs: object) -> None:
        _ = message, args, kwargs


def _make_order() -> UnifiedOrder:
    return UnifiedOrder(
        order_id="123",
        symbol="BTCUSDT",
        direction=OrderDirection.SELL,
        order_type=OrderType.LIMIT,
        volume=1.0,
        price=100.0,
        status="待成交",
        filled_volume=0.0,
        avg_price=0.0,
    )


class _CapableOwner:
    """模拟具备 reconcile、健康上报和下单探针能力的 owner."""

    channel_type = TradeChannel("external")

    def __init__(self) -> None:
        self.logger = _Logger()
        self.reconcile_calls: list[tuple[str, str]] = []
        self.ack_probes: list[str] = []
        self.health = OrderChannelHealth.DEGRADED
        self.terminal = _make_order()

    def reconcile_terminal_order(self, symbol: str, order_id: str) -> UnifiedOrder | None:
        self.reconcile_calls.append((symbol, order_id))
        return self.terminal

    def get_order_channel_health(self) -> OrderChannelHealth:
        return self.health

    def expect_order_ack(self, order_id: str) -> None:
        self.ack_probes.append(order_id)


class _PlainOwner:
    """模拟 CTP / GM owner：无 WebSocket 相关能力."""

    channel_type = TradeChannel.CTP

    def __init__(self) -> None:
        self.logger = _Logger()


def _session(owner: object) -> ExecutionSession:
    return ExecutionSession(owner=cast("Any", owner), symbol="BTCUSDT")


def test_session_proxies_reconcile_to_capable_owner() -> None:
    """owner 的 reconcile 应经 session 透传."""
    owner = _CapableOwner()
    session = _session(owner)

    result = session.reconcile_terminal_order("BTCUSDT", "123")

    assert owner.reconcile_calls == [("BTCUSDT", "123")]
    assert result is owner.terminal


def test_session_reconcile_returns_none_when_owner_incapable() -> None:
    """无能力 owner：reconcile 返回 None，等价跳过对账，不抛."""
    session = _session(_PlainOwner())
    assert session.reconcile_terminal_order("BTCUSDT", "123") is None


def test_session_proxies_channel_health() -> None:
    """owner 的健康度应经 session 透传."""
    owner = _CapableOwner()
    session = _session(owner)
    assert session.get_order_channel_health() == OrderChannelHealth.DEGRADED


def test_session_channel_health_unknown_when_owner_incapable() -> None:
    """无能力 owner：健康度回退 UNKNOWN，令 tracker 保持默认节奏."""
    session = _session(_PlainOwner())
    assert session.get_order_channel_health() == OrderChannelHealth.UNKNOWN


def test_session_proxies_expect_order_ack() -> None:
    """owner 的下单探针应经 session 登记."""
    owner = _CapableOwner()
    session = _session(owner)
    session.expect_order_ack("123")
    assert owner.ack_probes == ["123"]


def test_session_expect_order_ack_noop_when_owner_incapable() -> None:
    """无能力 owner：登记探针为无副作用空操作，不抛."""
    session = _session(_PlainOwner())
    session.expect_order_ack("123")

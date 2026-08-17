"""Execution query runtime bridge tests."""

from __future__ import annotations

from axile.executor.execution_query_runtime import ExecutionQueryRuntimeBridge
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder


def _make_order(symbol: str, order_id: str) -> UnifiedOrder:
    return UnifiedOrder(
        order_id=order_id,
        symbol=symbol,
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1.0,
        price=100.0,
        status="PENDING",
    )


def _make_trade(symbol: str, order_id: str, trade_id: str) -> TradeRecord:
    return TradeRecord.create(
        trade_id=trade_id,
        trade_time="2026-03-26T09:00:00",
        trade_volume=1.0,
        trade_price=100.0,
        order_id=order_id,
        extra={"symbol": symbol, "order_id": order_id},
    )


def test_bridge_patches_pending_snapshot_from_place_order_result() -> None:
    applied_orders: list[UnifiedOrder] = []

    class _Runtime:
        def apply_pending_order_update(self, order: UnifiedOrder) -> None:
            applied_orders.append(order)

    bridge = ExecutionQueryRuntimeBridge(
        type("_Owner", (), {"get_active_execution_query_runtime": lambda self: _Runtime()})()
    )
    order = _make_order("BTCUSDT", "order-1")

    patched = bridge.handle_place_order_result(order, fallback_symbol="BTCUSDT")

    assert patched is True
    assert applied_orders == [order]


def test_bridge_resolves_trade_invalidation_scope_from_trade_record() -> None:
    bridge = ExecutionQueryRuntimeBridge(
        type("_Owner", (), {"get_active_execution_query_runtime": lambda self: None})()
    )
    trade = _make_trade("ETHUSDT", "order-2", "trade-1")

    assert bridge.resolve_trade_invalidation_scope(trade) == ("ETHUSDT", "order-2")


def test_bridge_invalidates_trade_snapshot_when_patch_is_unavailable() -> None:
    invalidated: list[tuple[str | None, str | None]] = []

    class _Runtime:
        def invalidate_trades(self, symbol: str | None = None, order_id: str | None = None) -> None:
            invalidated.append((symbol, order_id))

    bridge = ExecutionQueryRuntimeBridge(
        type("_Owner", (), {"get_active_execution_query_runtime": lambda self: _Runtime()})()
    )
    trade = _make_trade("SOLUSDT", "order-3", "trade-2")

    patched = bridge.handle_trade_record(trade)

    assert patched is False
    assert invalidated == [("SOLUSDT", "order-3")]

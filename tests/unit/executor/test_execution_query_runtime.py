"""ExecutionQueryRuntime 共享查询语义测试。"""

from __future__ import annotations

import threading

from axile.executor.constants.order_status import OrderStatus
from axile.executor.execution_query_runtime import ExecutionQueryRuntime
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder


def _build_pending_order(symbol: str, order_id: str) -> UnifiedOrder:
    return UnifiedOrder(
        order_id=order_id,
        symbol=symbol,
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1.0,
        price=100.0,
        status=OrderStatus.PENDING,
    )


def _build_trade(symbol: str, order_id: str, trade_id: str) -> TradeRecord:
    return TradeRecord.create(
        trade_id=trade_id,
        trade_time="2026-03-25T09:00:00",
        trade_volume=1.0,
        trade_price=100.0,
        extra={"symbol": symbol, "order_id": order_id},
    )


def test_pending_order_snapshot_is_shared_across_symbols_until_invalidated() -> None:
    """snapshot-backed 挂单查询应只抓一次账户快照，再按 symbol 过滤。"""
    fetch_calls: list[str] = []

    def fetch_pending_orders_snapshot() -> list[UnifiedOrder]:
        fetch_calls.append("pending")
        return [
            _build_pending_order("BTCUSDT", "btc-order"),
            _build_pending_order("ETHUSDT", "eth-order"),
        ]

    runtime = ExecutionQueryRuntime(fetch_pending_orders_snapshot=fetch_pending_orders_snapshot)

    btc_orders = runtime.get_pending_orders_for_symbol("BTCUSDT")
    eth_orders = runtime.get_pending_orders_for_symbol("ETHUSDT")
    runtime.invalidate_all()
    btc_orders_after_invalidate = runtime.get_pending_orders_for_symbol("BTCUSDT")

    assert [order.order_id for order in btc_orders] == ["btc-order"]
    assert [order.order_id for order in eth_orders] == ["eth-order"]
    assert [order.order_id for order in btc_orders_after_invalidate] == ["btc-order"]
    assert fetch_calls == ["pending", "pending"]


def test_selective_invalidation_only_clears_target_snapshot() -> None:
    """orders/trades 级失效应只清理对应 snapshot。"""
    fetch_calls: list[str] = []

    def fetch_pending_orders_snapshot() -> list[UnifiedOrder]:
        fetch_calls.append("pending")
        return [_build_pending_order("BTCUSDT", "btc-order")]

    def fetch_trades_snapshot() -> list[TradeRecord]:
        fetch_calls.append("trades")
        return [_build_trade("BTCUSDT", "order-1", "trade-1")]

    runtime = ExecutionQueryRuntime(
        fetch_pending_orders_snapshot=fetch_pending_orders_snapshot,
        fetch_trades_snapshot=fetch_trades_snapshot,
    )

    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["btc-order"]
    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]

    runtime.invalidate_orders()
    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["btc-order"]
    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]

    runtime.invalidate_trades()
    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]

    assert fetch_calls == ["pending", "trades", "pending", "trades"]


def test_symbol_scoped_order_invalidation_keeps_other_symbols_cached_until_refresh() -> None:
    """只失效单个 symbol 的挂单时，不应让其他 symbol 立刻丢缓存。"""
    fetch_calls: list[str] = []

    def fetch_pending_orders_snapshot() -> list[UnifiedOrder]:
        fetch_calls.append("pending")
        return [
            _build_pending_order("BTCUSDT", "btc-order"),
            _build_pending_order("ETHUSDT", "eth-order"),
        ]

    runtime = ExecutionQueryRuntime(fetch_pending_orders_snapshot=fetch_pending_orders_snapshot)

    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["btc-order"]
    runtime.invalidate_orders("BTCUSDT")

    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("ETHUSDT")] == ["eth-order"]
    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["btc-order"]
    assert fetch_calls == ["pending", "pending"]


def test_order_scoped_trade_invalidation_keeps_other_orders_cached_until_refresh() -> None:
    """只失效单个 order_id 的成交时，不应让其他订单立刻丢缓存。"""
    fetch_calls: list[str] = []

    def fetch_trades_snapshot() -> list[TradeRecord]:
        fetch_calls.append("trades")
        return [
            _build_trade("BTCUSDT", "order-1", "trade-1"),
            _build_trade("BTCUSDT", "order-2", "trade-2"),
        ]

    runtime = ExecutionQueryRuntime(fetch_trades_snapshot=fetch_trades_snapshot)

    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]
    runtime.invalidate_trades("BTCUSDT", "order-1")

    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-2")] == ["trade-2"]
    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]
    assert fetch_calls == ["trades", "trades"]


def test_order_patch_updates_cached_pending_snapshot_without_refetch() -> None:
    """本地 order patch 应直接更新 pending snapshot，而不是触发新抓取。"""
    fetch_calls: list[str] = []

    def fetch_pending_orders_snapshot() -> list[UnifiedOrder]:
        fetch_calls.append("pending")
        return [_build_pending_order("BTCUSDT", "btc-order")]

    runtime = ExecutionQueryRuntime(fetch_pending_orders_snapshot=fetch_pending_orders_snapshot)

    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["btc-order"]

    updated_order = _build_pending_order("BTCUSDT", "btc-order")
    updated_order.price = 101.5
    runtime.apply_pending_order_update(updated_order)

    patched_orders = runtime.get_pending_orders_for_symbol("BTCUSDT")
    assert len(patched_orders) == 1
    assert patched_orders[0].price == 101.5
    assert fetch_calls == ["pending"]


def test_trade_patch_updates_cached_trade_snapshot_without_touching_pending_order() -> None:
    """本地 trade patch 只应更新 trades snapshot，不应反向 patch pending order。"""
    order_fetch_calls: list[str] = []
    trade_fetch_calls: list[str] = []

    pending_order = _build_pending_order("BTCUSDT", "order-1")
    pending_order.volume = 2.0

    def fetch_pending_orders_snapshot() -> list[UnifiedOrder]:
        order_fetch_calls.append("pending")
        return [pending_order.model_copy(deep=True)]

    def fetch_trades_snapshot() -> list[TradeRecord]:
        trade_fetch_calls.append("trades")
        return []

    runtime = ExecutionQueryRuntime(
        fetch_pending_orders_snapshot=fetch_pending_orders_snapshot,
        fetch_trades_snapshot=fetch_trades_snapshot,
    )

    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["order-1"]
    assert runtime.get_trades_for_order("BTCUSDT", "order-1") == []

    runtime.apply_trade_record(_build_trade("BTCUSDT", "order-1", "trade-1"))

    patched_trades = runtime.get_trades_for_order("BTCUSDT", "order-1")
    patched_orders = runtime.get_pending_orders_for_symbol("BTCUSDT")
    assert [trade.trade_id for trade in patched_trades] == ["trade-1"]
    assert len(patched_orders) == 1
    assert patched_orders[0].filled_volume == 0.0
    assert trade_fetch_calls == ["trades"]
    assert order_fetch_calls == ["pending"]


def test_order_patch_does_not_clear_trade_dirty_scope() -> None:
    """order patch 属于订单域，不应顺手清理 trades dirty marker。"""
    trade_fetch_calls: list[str] = []

    def fetch_trades_snapshot() -> list[TradeRecord]:
        trade_fetch_calls.append("trades")
        return [_build_trade("BTCUSDT", "order-1", "trade-1")]

    runtime = ExecutionQueryRuntime(fetch_trades_snapshot=fetch_trades_snapshot)

    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]
    runtime.invalidate_trades("BTCUSDT", "order-1")
    runtime.apply_pending_order_update(_build_pending_order("BTCUSDT", "order-1"))
    assert [trade.trade_id for trade in runtime.get_trades_for_order("BTCUSDT", "order-1")] == ["trade-1"]
    assert trade_fetch_calls == ["trades", "trades"]


def test_trade_patch_does_not_clear_order_dirty_scope() -> None:
    """trade patch 属于成交域，不应顺手清理 orders dirty marker。"""
    order_fetch_calls: list[str] = []

    def fetch_pending_orders_snapshot() -> list[UnifiedOrder]:
        order_fetch_calls.append("pending")
        return [_build_pending_order("BTCUSDT", "order-1")]

    runtime = ExecutionQueryRuntime(fetch_pending_orders_snapshot=fetch_pending_orders_snapshot)

    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["order-1"]
    runtime.invalidate_orders("BTCUSDT")
    runtime.apply_trade_record(_build_trade("BTCUSDT", "order-1", "trade-1"))
    assert [order.order_id for order in runtime.get_pending_orders_for_symbol("BTCUSDT")] == ["order-1"]
    assert order_fetch_calls == ["pending", "pending"]


def test_trade_snapshot_singleflights_concurrent_joiners_and_filters_per_order() -> None:
    """同一份 trades snapshot 应允许多个 joiner 共享一次远端抓取。"""
    fetch_started = threading.Event()
    release_fetch = threading.Event()
    fetch_count = 0
    fetch_count_lock = threading.Lock()

    def fetch_trades_snapshot() -> list[TradeRecord]:
        nonlocal fetch_count
        with fetch_count_lock:
            fetch_count += 1
        fetch_started.set()
        release_fetch.wait(timeout=1)
        return [
            _build_trade("BTCUSDT", "order-1", "trade-1"),
            _build_trade("ETHUSDT", "order-2", "trade-2"),
        ]

    runtime = ExecutionQueryRuntime(fetch_trades_snapshot=fetch_trades_snapshot)
    results: dict[str, list[TradeRecord]] = {}

    def read_btc() -> None:
        results["btc"] = runtime.get_trades_for_order("BTCUSDT", "order-1")

    def read_eth() -> None:
        results["eth"] = runtime.get_trades_for_order("ETHUSDT", "order-2")

    btc_thread = threading.Thread(target=read_btc)
    eth_thread = threading.Thread(target=read_eth)
    btc_thread.start()
    fetch_started.wait(timeout=1)
    eth_thread.start()
    release_fetch.set()
    btc_thread.join()
    eth_thread.join()

    assert fetch_count == 1
    assert [trade.trade_id for trade in results["btc"]] == ["trade-1"]
    assert [trade.trade_id for trade in results["eth"]] == ["trade-2"]


def test_narrow_trade_query_only_singleflights_identical_inflight_requests() -> None:
    """narrow-query 不做全局缓存，只对相同 query key 的并发请求去重。"""
    fetch_started = threading.Event()
    release_fetch = threading.Event()
    fetch_calls: list[tuple[str, str]] = []
    results: list[list[TradeRecord]] = []

    def fetch_trades_by_order(symbol: str, order_id: str) -> list[TradeRecord]:
        fetch_calls.append((symbol, order_id))
        fetch_started.set()
        release_fetch.wait(timeout=1)
        return [_build_trade(symbol, order_id, f"trade-{order_id}")]

    runtime = ExecutionQueryRuntime(fetch_trades_by_order=fetch_trades_by_order)

    def read_once() -> None:
        results.append(runtime.get_trades_for_order("BTCUSDT", "order-1"))

    first = threading.Thread(target=read_once)
    second = threading.Thread(target=read_once)
    first.start()
    fetch_started.wait(timeout=1)
    second.start()
    release_fetch.set()
    first.join()
    second.join()

    third_result = runtime.get_trades_for_order("BTCUSDT", "order-1")

    assert fetch_calls == [("BTCUSDT", "order-1"), ("BTCUSDT", "order-1")]
    assert [[trade.trade_id for trade in batch] for batch in results] == [["trade-order-1"], ["trade-order-1"]]
    assert [trade.trade_id for trade in third_result] == ["trade-order-1"]

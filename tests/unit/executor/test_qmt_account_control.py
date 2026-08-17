"""QMT 账户控制打点测试。"""

from __future__ import annotations

import importlib
import inspect
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.models import (
    AccountControlDecision,
    AccountControlOverride,
)
from axile.executor.account_control.presets import resolve_account_control_policy
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from tests.unit.executor._account_control_test_support import normalize_account_control_override
from tests.unit.executor._qmt_test_support import install_qmt_stubs as _install_qmt_stubs


def test_convert_qmt_order_to_unified_accepts_order_only() -> None:
    """QMT 订单转换器应保持纯订单接口，不再接受成交列表。"""
    from axile.executor.qmt.converters.order_converter import convert_qmt_order_to_unified

    assert tuple(inspect.signature(convert_qmt_order_to_unified).parameters) == ("qmt_order",)


def test_qmt_client_helpers_are_reexported_from_dedicated_module() -> None:
    """QMT 启动与初始化 helper 应拆到独立模块，同时保持旧入口兼容。"""
    module_name = "axile.executor.qmt.core.qmt_client"
    assert importlib.util.find_spec(module_name) is not None

    qmt_client_module = importlib.import_module(module_name)
    qmt_execute_module = importlib.import_module("axile.executor.qmt.qmt_execute")
    qmt_package_module = importlib.import_module("axile.executor.qmt")

    for helper_name in (
        "find_exe_window",
        "close_exe_window",
        "wait_qmt_ready",
        "initialize_qmt",
        "start_qmt_exe",
    ):
        dedicated_helper = getattr(qmt_client_module, helper_name)
        assert getattr(qmt_execute_module, helper_name) is dedicated_helper
        assert getattr(qmt_package_module, helper_name) is dedicated_helper


_install_qmt_stubs()

from axile.executor.qmt.core.callback_dispatcher import QMTCallbackDispatcher
from axile.executor.qmt.qmt_execute import QMTExecutor


class _LoggerStub:
    def info(self, _message: object) -> None:
        pass

    def warning(self, _message: object) -> None:
        pass

    def error(self, _message: object) -> None:
        pass

    def exception(self, _message: object) -> None:
        pass


class _XtTraderStub:
    def __init__(self) -> None:
        self.connected = True
        self.order_calls: list[dict[str, Any]] = []
        self.query_order_calls: list[bool] = []
        self.query_trade_calls = 0
        self.cancel_calls: list[int] = []
        self.orders: list[Any] = []
        self.trades: list[Any] = []

    def start(self) -> None:
        self.connected = True

    def connect(self) -> None:
        self.connected = True

    def order_stock(self, **kwargs: Any) -> int:
        self.order_calls.append(kwargs)
        return len(self.order_calls)

    def query_stock_orders(self, _acc: object, *, cancelable_only: bool) -> list[Any]:
        self.query_order_calls.append(cancelable_only)
        return self.orders

    def query_stock_trades(self, _acc: object) -> list[Any]:
        self.query_trade_calls += 1
        return self.trades

    def cancel_order_stock(self, _acc: object, order_id: int) -> int:
        self.cancel_calls.append(order_id)
        return 0


def _clock() -> datetime:
    return datetime(2026, 3, 22, 9, 31, 15)


def _clock_from(*moments: datetime):
    sequence = iter(moments)

    def _inner() -> datetime:
        return next(sequence)

    return _inner


def _build_guard(
    override: dict[str, Any],
    *,
    clock: Any | None = None,
    sleep: Any | None = None,
    wait_poll_interval_ms: int = 100,
) -> AccountControlGuard:
    normalized_override = normalize_account_control_override(override)
    return AccountControlGuard(
        account_id=21,
        execution_id="exec-qmt",
        channel=TradeChannel.QMT,
        policy=resolve_account_control_policy(
            "default",
            AccountControlOverride.model_validate(normalized_override),
        ),
        baseline=AccountControlCounterSnapshot(),
        clock=_clock if clock is None else clock,
        sleep=sleep,
        wait_poll_interval_ms=wait_poll_interval_ms,
    )


def _build_executor(guard: AccountControlGuard, xtt: _XtTraderStub) -> QMTExecutor:
    executor = QMTExecutor.__new__(QMTExecutor)
    executor.channel_type = TradeChannel.QMT
    executor.logger = _LoggerStub()
    executor.xtt = xtt
    executor.acc = object()
    executor.set_account_control_guard(guard)
    return executor


def _make_qmt_order(symbol: str, order_id: int, order_time: float) -> Any:
    return SimpleNamespace(
        order_id=order_id,
        stock_code=symbol,
        order_type=23,
        price_type=11,
        order_volume=100,
        price=12.3,
        order_status=50,
        order_time=order_time,
        traded_volume=0,
        traded_price=0.0,
        order_remark="remark",
        strategy_name="strategy",
        status_msg="ok",
        direction=23,
        offset_flag=0,
        order_sysid=f"sys-{order_id}",
        secu_account="acc",
        instrument_name=symbol,
    )


def _make_qmt_trade(symbol: str, order_id: int, traded_id: int, traded_time: float) -> Any:
    return SimpleNamespace(
        order_id=order_id,
        stock_code=symbol,
        traded_id=traded_id,
        traded_time=traded_time,
        traded_volume=100,
        traded_price=12.3,
        traded_amount=1230.0,
        offset_flag=0,
        direction=23,
        order_sysid=f"sys-{order_id}",
        commission=1.0,
        secu_account="acc",
        instrument_name=symbol,
    )


def test_place_order_symbol_scope_blocks_only_matching_symbol() -> None:
    """operations.symbol 配置应只阻断命中的 symbol，不影响其他 symbol。"""
    xtt = _XtTraderStub()
    guard = _build_guard(
        {
            "operations": {
                "place_order": {
                    "account": {
                        "per_day": {"limit": 2, "on_trigger": "block"},
                        "min_interval_ms": {"limit": 1, "on_trigger": "block"},
                    },
                    "symbol": {
                        "per_day": {"limit": 1, "on_trigger": "block"},
                        "min_interval_ms": {"limit": 1, "on_trigger": "block"},
                    },
                }
            },
        },
        clock=_clock_from(
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 2000),
        ),
    )
    executor = _build_executor(guard, xtt)

    executor.place_order("600000.SH", OrderDirection.BUY, OrderType.LIMIT, 100, price=12.3)

    with pytest.raises(AccountControlBlockedError):
        executor.place_order("600000.SH", OrderDirection.BUY, OrderType.LIMIT, 100, price=12.4)

    executor.place_order("000001.SZ", OrderDirection.BUY, OrderType.LIMIT, 100, price=8.9)

    assert [call["stock_code"] for call in xtt.order_calls] == ["600000.SH", "000001.SZ"]

    _, events = guard.flush_records()
    assert [event.decision for event in events] == [
        AccountControlDecision.ALLOWED,
        AccountControlDecision.BLOCKED,
        AccountControlDecision.ALLOWED,
    ]
    assert [event.symbol for event in events] == ["600000.SH", "600000.SH", "000001.SZ"]


def test_get_pending_orders_records_single_query_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """公开 get_pending_orders(symbol) 只按一次 query_order 预算记账。"""
    xtt = _XtTraderStub()
    xtt.orders = [_make_qmt_order("600000.SH", 1, order_time=time.time())]
    guard = _build_guard({"query_order": {"per_day": 2}})
    executor = _build_executor(guard, xtt)
    monkeypatch.setattr(executor, "get_all_symbols", lambda: ["600000.SH"])

    orders = executor.get_pending_orders("600000.SH")

    assert len(orders) == 1
    assert xtt.query_order_calls == [True]
    assert xtt.query_trade_calls == 0

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].outcome != "pending"


def test_get_pending_orders_with_none_returns_all_cancelable_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """公开 get_pending_orders(None) 应返回账户全部可撤订单。"""
    xtt = _XtTraderStub()
    xtt.orders = [
        _make_qmt_order("600000.SH", 1, order_time=time.time()),
        _make_qmt_order("000001.SZ", 2, order_time=time.time()),
    ]
    guard = _build_guard({"query_order": {"per_day": 1}})
    executor = _build_executor(guard, xtt)
    monkeypatch.setattr(executor, "get_all_symbols", lambda: ["600000.SH", "000001.SZ"])

    orders = executor.get_pending_orders(None)

    assert len(orders) == 2
    assert {order.symbol for order in orders} == {"600000.SH", "000001.SZ"}
    assert xtt.query_order_calls == [True]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].symbol is None


def test_query_order_records_returns_unified_orders() -> None:
    """QMT 应提供统一 UnifiedOrder 级别的订单 helper。"""
    xtt = _XtTraderStub()
    xtt.orders = [
        _make_qmt_order("600000.SH", 1, order_time=time.time()),
        _make_qmt_order("000001.SZ", 2, order_time=time.time()),
    ]
    executor = _build_executor(_build_guard({}), xtt)

    orders = executor._query_order_records(cancelable_only=True)  # pyright: ignore[reportPrivateUsage]

    assert [order.order_id for order in orders] == ["1", "2"]
    assert [order.symbol for order in orders] == ["600000.SH", "000001.SZ"]
    assert [order.extra["order_sysid"] for order in orders] == ["sys-1", "sys-2"]
    assert xtt.query_order_calls == [True]


def test_query_trades_records_single_query_trades_budget() -> None:
    """公开 query_trades 只按一次 query_trades 预算记账。"""
    xtt = _XtTraderStub()
    xtt.trades = [
        _make_qmt_trade("600000.SH", 1, traded_id=11, traded_time=time.time()),
        _make_qmt_trade("000001.SZ", 2, traded_id=22, traded_time=time.time()),
    ]
    guard = _build_guard({"query_trades": {"per_day": 1}})
    executor = _build_executor(guard, xtt)

    trades = executor.query_trades("600000.SH", "1")

    assert [trade.trade_id for trade in trades] == ["11"]
    assert xtt.query_trade_calls == 1

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_trades"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].metadata == {"order_id": "1"}


def test_query_trade_records_returns_unified_trade_records() -> None:
    """QMT 应提供统一 TradeRecord 级别的全量成交 helper。"""
    xtt = _XtTraderStub()
    xtt.trades = [
        _make_qmt_trade("600000.SH", 1, traded_id=11, traded_time=time.time()),
        _make_qmt_trade("000001.SZ", 2, traded_id=22, traded_time=time.time()),
    ]
    executor = _build_executor(_build_guard({}), xtt)

    trade_records = executor._query_trade_records()  # pyright: ignore[reportPrivateUsage]

    assert [trade.trade_id for trade in trade_records] == ["11", "22"]
    assert [trade.symbol for trade in trade_records] == ["600000.SH", "000001.SZ"]
    assert [trade.order_id for trade in trade_records] == ["1", "2"]
    assert [trade.extra["order_sysid"] for trade in trade_records] == ["sys-1", "sys-2"]
    assert xtt.query_trade_calls == 1


def test_execution_internal_pending_orders_share_snapshot_and_single_query_event() -> None:
    """execution-internal 挂单查询应共享一次 QMT 账户级 snapshot fetch。"""
    xtt = _XtTraderStub()
    xtt.orders = [
        _make_qmt_order("600000.SH", 1, order_time=time.time()),
        _make_qmt_order("000001.SZ", 2, order_time=time.time()),
    ]
    guard = _build_guard({"query_order": {"per_day": 1}})
    executor = _build_executor(guard, xtt)

    sh_orders = executor._get_pending_orders_for_execution("600000.SH")
    sz_orders = executor._get_pending_orders_for_execution("000001.SZ")

    assert [order.order_id for order in sh_orders] == ["1"]
    assert [order.order_id for order in sz_orders] == ["2"]
    assert xtt.query_order_calls == [True]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].symbol is None
    assert events[0].metadata["query_scope"] == "snapshot"


def test_callback_dispatch_invalidates_execution_query_runtime() -> None:
    """QMT 订单和成交回调到达时应 patch execution 共享查询快照。"""
    executor = QMTExecutor.__new__(QMTExecutor)
    executor.channel_type = TradeChannel.QMT
    executor.logger = _LoggerStub()
    executor._callback_dispatcher = QMTCallbackDispatcher()
    patched_orders: list[UnifiedOrder] = []
    patched_trades: list[TradeRecord] = []

    class _Runtime:
        def apply_pending_order_update(self, order: UnifiedOrder) -> None:
            patched_orders.append(order)

        def apply_trade_record(self, trade: TradeRecord) -> None:
            patched_trades.append(trade)

    executor.set_active_execution_query_runtime(_Runtime())
    QMTExecutor._register_execution_query_runtime_callback_observers(executor)

    order = UnifiedOrder.create(
        order_id="1",
        symbol="600000.SH",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=100,
        price=12.3,
        status="已报",
        channel_type=TradeChannel.QMT,
    )
    trade = TradeRecord.create(
        trade_id="11",
        trade_time="2026-03-22T09:31:15",
        trade_volume=100,
        trade_price=12.3,
        extra={"symbol": "600000.SH", "order_id": "1"},
    )
    executor._callback_dispatcher.dispatch_order_update(order)
    executor._callback_dispatcher.dispatch_trade_record(trade)

    assert patched_orders == [order]
    assert patched_trades == [trade]


def test_cancel_order_consumes_cancel_order_budget() -> None:
    """QMT 撤单路径应按 cancel_order 预算计数。"""
    xtt = _XtTraderStub()
    guard = _build_guard({"cancel_order": {"per_day": 1}})
    executor = _build_executor(guard, xtt)

    assert executor.cancel_order("600000.SH", "123") is True
    assert xtt.cancel_calls == [123]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "cancel_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].metadata == {"order_id": "123"}
    assert events[0].outcome != "pending"


def test_place_order_min_interval_waits_before_second_stock_order_call() -> None:
    """命中 min_interval_ms 后，第二次 QMT 下单应等待后继续触发真实委托。"""
    xtt = _XtTraderStub()
    sleep_calls: list[float] = []
    guard = _build_guard(
        {"place_order": {"per_day": 5, "min_interval_ms": 500}},
        clock=_clock_from(
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 200000),
            datetime(2026, 3, 22, 9, 31, 15, 500000),
        ),
        sleep=sleep_calls.append,
        wait_poll_interval_ms=500,
    )
    executor = _build_executor(guard, xtt)

    executor.place_order("600000.SH", OrderDirection.BUY, OrderType.LIMIT, 100, price=12.3)
    executor.place_order("600000.SH", OrderDirection.BUY, OrderType.LIMIT, 100, price=12.4)

    assert sleep_calls == pytest.approx([0.3])
    assert len(xtt.order_calls) == 2

    _, events = guard.flush_records()
    assert all(event.decision == AccountControlDecision.ALLOWED for event in events)

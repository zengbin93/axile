"""GM 账户控制打点测试。"""

from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType
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
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from tests.unit.executor._account_control_test_support import normalize_account_control_override


def _install_gm_stubs() -> None:
    gm_module = sys.modules.setdefault("gm", ModuleType("gm"))
    api_module = sys.modules.setdefault("gm.api", ModuleType("gm.api"))
    csdk_module = sys.modules.setdefault("gm.csdk", ModuleType("gm.csdk"))
    c_sdk_module = sys.modules.setdefault("gm.csdk.c_sdk", ModuleType("gm.csdk.c_sdk"))
    pb_module = sys.modules.setdefault("gm.pb", ModuleType("gm.pb"))
    account_pb2_module = sys.modules.setdefault("gm.pb.account_pb2", ModuleType("gm.pb.account_pb2"))
    tradegw_pb2_module = sys.modules.setdefault(
        "gm.pb.tradegw_service_pb2",
        ModuleType("gm.pb.tradegw_service_pb2"),
    )

    api_module.OrderSide_Buy = 1
    api_module.OrderSide_Sell = 2
    api_module.OrderType_Limit = 1
    api_module.OrderType_Market = 2
    api_module.PositionEffect_Close = 2
    api_module.PositionEffect_Open = 1
    api_module.current = lambda *_args, **_kwargs: None
    api_module.get_cash = lambda *_args, **_kwargs: None
    api_module.get_execution_reports = lambda *_args, **_kwargs: []
    api_module.get_orders = lambda *_args, **_kwargs: []
    api_module.get_position = lambda *_args, **_kwargs: None
    api_module.get_unfinished_orders = lambda *_args, **_kwargs: []
    api_module.order_cancel = lambda *_args, **_kwargs: None
    api_module.order_volume = lambda *_args, **_kwargs: []
    api_module.set_account_id = lambda *_args, **_kwargs: None
    api_module.set_serv_addr = lambda *_args, **_kwargs: None
    api_module.set_token = lambda *_args, **_kwargs: None
    api_module.subscribe = lambda *_args, **_kwargs: None
    api_module.timer = lambda *_args, **_kwargs: {"timer_id": 10001, "status": 0}
    api_module.timer_stop = lambda *_args, **_kwargs: True

    c_sdk_module.c_status_fail = -1
    c_sdk_module.py_gmi_get_account_status = lambda *_args, **_kwargs: 0

    class AccountStatuses:
        pass

    class GetAccountStatusesReq:
        pass

    account_pb2_module.AccountStatuses = AccountStatuses
    tradegw_pb2_module.GetAccountStatusesReq = GetAccountStatusesReq

    gm_module.api = api_module
    gm_module.csdk = csdk_module
    gm_module.pb = pb_module
    csdk_module.c_sdk = c_sdk_module
    pb_module.account_pb2 = account_pb2_module
    pb_module.tradegw_service_pb2 = tradegw_pb2_module


_install_gm_stubs()

from axile.executor.execution_session import ExecutionSession
from axile.executor.gm import gm_execute as gm_execute_module
from axile.executor.gm.core import api_bridge as gm_api_bridge_module
from axile.executor.gm.gm_execute import GMExecutor
from axile.executor.termination import ExecutionTerminated


class _LoggerStub:
    def info(self, _message: object) -> None:
        pass

    def warning(self, _message: object) -> None:
        pass

    def error(self, _message: object) -> None:
        pass

    def exception(self, _message: object) -> None:
        pass


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
        account_id=7,
        execution_id="exec-gm",
        channel=TradeChannel.GM,
        policy=resolve_account_control_policy(
            "default",
            AccountControlOverride.model_validate(normalized_override),
        ),
        baseline=AccountControlCounterSnapshot(),
        clock=_clock if clock is None else clock,
        sleep=sleep,
        wait_poll_interval_ms=wait_poll_interval_ms,
    )


def _build_executor(guard: AccountControlGuard) -> GMExecutor:
    executor = GMExecutor.__new__(GMExecutor)
    executor.account_id = "gm-account"
    executor.channel_type = TradeChannel.GM
    executor.account_config = None
    executor.logger = _LoggerStub()
    executor.audit_context = {}
    executor.require_execution_runtime().memory = {}
    executor.set_account_control_guard(guard)
    executor._execution_order_ids = set()
    executor.set_termination_controller(None)
    executor._call_bridge = lambda request, timeout=30.0: {  # type: ignore[method-assign]
        "get_position": gm_api_bridge_module.get_position,
        "get_cash": gm_api_bridge_module.get_cash,
        "current": gm_api_bridge_module.current,
        "get_unfinished_orders": gm_api_bridge_module.get_unfinished_orders,
        "get_execution_reports": gm_api_bridge_module.get_execution_reports,
        "get_orders": gm_api_bridge_module.get_orders,
        "order_cancel": gm_api_bridge_module.order_cancel,
        "order_volume": gm_api_bridge_module.order_volume,
    }[request.operation](**request.as_kwargs())
    return executor


def test_place_order_blocked_before_real_order_volume_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中 place_order 限制时不应继续触发真实 GM 下单。"""
    guard = _build_guard({"place_order": {"per_day": 0}})
    executor = _build_executor(guard)
    order_volume_calls: list[dict[str, Any]] = []

    def fake_order_volume(**kwargs: Any) -> list[dict[str, Any]]:
        order_volume_calls.append(kwargs)
        return [{"cl_ord_id": "gm-cl-1"}]

    monkeypatch.setattr(gm_api_bridge_module, "order_volume", fake_order_volume)

    with pytest.raises(AccountControlBlockedError):
        executor.place_order(
            symbol="SHSE.600000",
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=100,
            price=12.3,
        )

    assert order_volume_calls == []

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "place_order"
    assert events[0].decision == AccountControlDecision.BLOCKED
    assert events[0].symbol == "SHSE.600000"


def test_cancel_order_consumes_cancel_order_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """GM 单笔撤单应按 cancel_order 预算记账。"""
    guard = _build_guard({"cancel_order": {"per_day": 1}})
    executor = _build_executor(guard)
    cancel_calls: list[list[dict[str, str]]] = []

    def fake_order_cancel(*, wait_cancel_orders: list[dict[str, str]]) -> None:
        cancel_calls.append(wait_cancel_orders)

    monkeypatch.setattr(gm_api_bridge_module, "order_cancel", fake_order_cancel)

    assert executor.cancel_order("SHSE.600000", "gm-oid-1") is True
    assert cancel_calls == [[{"cl_ord_id": "gm-oid-1", "account_id": "gm-account"}]]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "cancel_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].metadata == {"order_id": "gm-oid-1"}
    assert events[0].outcome != "pending"


def test_pending_order_fetches_record_single_query_order_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """公开 get_pending_orders 只按一次 query_order 预算记账。"""
    guard = _build_guard(
        {"query_order": {"per_day": 2}},
        clock=_clock_from(
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 200000),
        ),
    )
    executor = _build_executor(guard)
    query_calls: list[str] = []
    created_at = datetime(2026, 3, 22, 9, 30, 0)

    def fake_get_unfinished_orders(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("unfinished")
        return [
            {
                "account_id": "gm-account",
                "order_id": "1001",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 100,
                "price": 12.3,
                "status": 1,
                "created_at": created_at,
            }
        ]

    def fake_get_execution_reports(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("reports")
        return []

    monkeypatch.setattr(gm_api_bridge_module, "get_unfinished_orders", fake_get_unfinished_orders)
    monkeypatch.setattr(gm_api_bridge_module, "get_execution_reports", fake_get_execution_reports)

    orders = executor.get_pending_orders("SHSE.600000")

    assert query_calls == ["unfinished"]
    assert len(orders) == 1
    assert orders[0].order_id == "gm-cl-1"
    assert orders[0].extra["exchange_order_id"] == "1001"

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].outcome != "pending"


def test_pending_order_fetch_records_single_public_query_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """公开 get_pending_orders 只记一次 QUERY_ORDER，内部富化查询不再单独计数。"""
    guard = _build_guard(
        {"query_order": {"per_day": 1}},
    )
    executor = _build_executor(guard)
    query_calls: list[str] = []

    def fake_get_unfinished_orders(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("unfinished")
        return []

    def fake_get_execution_reports(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("reports")
        return []

    monkeypatch.setattr(gm_api_bridge_module, "get_unfinished_orders", fake_get_unfinished_orders)
    monkeypatch.setattr(gm_api_bridge_module, "get_execution_reports", fake_get_execution_reports)

    assert executor.get_pending_orders("SHSE.600000") == []

    assert query_calls == ["unfinished"]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].operation == "query_order"


def test_query_trades_records_single_query_trades_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """公开 query_trades 只按一次 query_trades 预算记账。"""
    guard = _build_guard({"query_trades": {"per_day": 1}})
    executor = _build_executor(guard)
    query_calls: list[str] = []
    created_at = datetime(2026, 3, 22, 9, 30, 0)

    def fake_get_execution_reports(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("reports")
        return [
            {
                "account_id": "gm-account",
                "exec_id": "exec-1",
                "cl_ord_id": "gm-cl-1",
                "order_id": "exchange-1",
                "symbol": "SHSE.600000",
                "volume": 100,
                "price": 12.3,
                "created_at": created_at,
            },
            {
                "account_id": "gm-account",
                "exec_id": "exec-2",
                "cl_ord_id": "gm-cl-2",
                "order_id": "exchange-2",
                "symbol": "SZSE.000001",
                "volume": 200,
                "price": 8.9,
                "created_at": created_at,
            },
        ]

    monkeypatch.setattr(gm_api_bridge_module, "get_execution_reports", fake_get_execution_reports)

    trades = executor.query_trades("SHSE.600000", "gm-cl-1")

    assert query_calls == ["reports"]
    assert [trade.extra["cl_ord_id"] for trade in trades] == ["gm-cl-1"]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_trades"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].metadata == {"order_id": "gm-cl-1"}


def test_execution_internal_pending_orders_share_snapshot_and_single_query_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execution-internal 挂单查询应共享一次 GM 账户级 snapshot fetch。"""
    guard = _build_guard({"query_order": {"per_day": 1}})
    executor = _build_executor(guard)
    query_calls: list[str] = []
    created_at = datetime(2026, 3, 22, 9, 30, 0)

    def fake_get_unfinished_orders(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("unfinished")
        return [
            {
                "account_id": "gm-account",
                "order_id": "1001",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 100,
                "price": 12.3,
                "status": 1,
                "created_at": created_at,
            },
            {
                "account_id": "gm-account",
                "order_id": "1002",
                "cl_ord_id": "gm-cl-2",
                "symbol": "SZSE.000001",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 200,
                "price": 8.9,
                "status": 1,
                "created_at": created_at,
            },
        ]

    def fake_get_execution_reports(**_kwargs: Any) -> list[dict[str, Any]]:
        query_calls.append("reports")
        return []

    monkeypatch.setattr(gm_api_bridge_module, "get_unfinished_orders", fake_get_unfinished_orders)
    monkeypatch.setattr(gm_api_bridge_module, "get_execution_reports", fake_get_execution_reports)

    sh_orders = executor._get_pending_orders_for_execution("SHSE.600000")
    sz_orders = executor._get_pending_orders_for_execution("SZSE.000001")

    assert [order.order_id for order in sh_orders] == ["gm-cl-1"]
    assert [order.order_id for order in sz_orders] == ["gm-cl-2"]
    assert query_calls == ["unfinished"]

    _, events = guard.flush_records()
    assert len(events) == 1
    assert events[0].operation == "query_order"
    assert events[0].decision == AccountControlDecision.ALLOWED
    assert events[0].symbol is None
    assert events[0].metadata["query_scope"] == "snapshot"


def test_callback_dispatch_invalidates_execution_query_runtime() -> None:
    """GM 订单和成交回调到达时应 patch execution 共享查询快照。"""
    executor = GMExecutor.__new__(GMExecutor)
    executor.channel_type = TradeChannel.GM
    executor.logger = _LoggerStub()
    executor._callback_dispatcher = gm_execute_module.GMCallbackDispatcher()
    patched_orders: list[UnifiedOrder] = []
    patched_trades: list[TradeRecord] = []

    class _Runtime:
        def apply_pending_order_update(self, order: UnifiedOrder) -> None:
            patched_orders.append(order)

        def apply_trade_record(self, trade: TradeRecord) -> None:
            patched_trades.append(trade)

    executor.set_active_execution_query_runtime(_Runtime())
    GMExecutor._register_execution_query_runtime_callback_observers(executor)

    order = UnifiedOrder.create(
        order_id="gm-cl-1",
        symbol="SHSE.600000",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=100,
        price=12.3,
        status=OrderStatus.PENDING,
        channel_type=TradeChannel.GM,
    )
    trade = TradeRecord.create(
        trade_id="trade-1",
        trade_time="2026-03-22T09:31:15",
        trade_volume=100,
        trade_price=12.3,
        extra={"symbol": "SHSE.600000", "cl_ord_id": "gm-cl-1"},
    )
    executor._callback_dispatcher.dispatch_order_update(order)
    executor._callback_dispatcher.dispatch_trade_record(trade)

    assert patched_orders == [order]
    assert patched_trades == [trade]


def test_place_order_min_interval_waits_before_second_real_order_volume_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命中 min_interval_ms 后，第二次 GM 下单应等待后继续触发真实委托。"""
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
    executor = _build_executor(guard)
    order_volume_calls: list[dict[str, Any]] = []

    def fake_order_volume(**kwargs: Any) -> list[dict[str, Any]]:
        order_volume_calls.append(kwargs)
        return [{"cl_ord_id": f"gm-cl-{len(order_volume_calls)}"}]

    monkeypatch.setattr(gm_api_bridge_module, "order_volume", fake_order_volume)

    executor.place_order(
        symbol="SHSE.600000",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=100,
        price=12.3,
    )
    executor.place_order(
        symbol="SHSE.600000",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=100,
        price=12.4,
    )

    assert sleep_calls == pytest.approx([0.3])
    assert len(order_volume_calls) == 2

    _, events = guard.flush_records()
    assert all(event.decision == AccountControlDecision.ALLOWED for event in events)


def test_place_order_returns_provisional_order_without_followup_sync_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GM 下单后直接返回 submitted order，不再发起同步查单/成交富化查询。"""
    guard = _build_guard({"place_order": {"per_day": 1}, "query_order": {"per_day": 1}})
    executor = _build_executor(guard)
    get_orders_calls: list[str] = []
    get_execution_report_calls: list[str] = []

    monkeypatch.setattr(gm_api_bridge_module, "order_volume", lambda **_kwargs: [{"cl_ord_id": "gm-cl-1"}])
    monkeypatch.setattr(gm_api_bridge_module, "get_orders", lambda **_kwargs: get_orders_calls.append("called") or [])
    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_execution_reports",
        lambda **_kwargs: get_execution_report_calls.append("called") or [],
    )

    order = executor.place_order(
        symbol="SHSE.600000",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=100,
        price=12.3,
    )

    assert order.order_id == "gm-cl-1"
    assert order.status == OrderStatus.SUBMITTED
    assert get_orders_calls == []
    assert get_execution_report_calls == []

    _, events = guard.flush_records()
    assert [event.operation for event in events] == ["place_order"]
    assert all(event.decision == AccountControlDecision.ALLOWED for event in events)
    assert all(event.outcome != "pending" for event in events)


def test_filter_recent_orders_uses_query_budget_for_order_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recent-order 辅助查询属于内部实现细节，不再单独计 query_order。"""
    guard = _build_guard(
        {"query_order": {"per_day": 1}},
        clock=_clock_from(
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 0),
            datetime(2026, 3, 22, 9, 31, 15, 200000),
        ),
    )
    executor = _build_executor(guard)
    get_orders_calls: list[str] = []
    execution_report_calls: list[str] = []

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_execution_reports",
        lambda **_kwargs: execution_report_calls.append("called") or [],
    )
    monkeypatch.setattr(gm_api_bridge_module, "get_orders", lambda **_kwargs: get_orders_calls.append("called") or [])

    assert executor._filter_recent_orders(within_seconds=120, account_id="gm-account") == []

    assert execution_report_calls == []
    assert get_orders_calls == ["called"]

    _, events = guard.flush_records()
    assert events == []


def test_symbol_pending_cancel_records_single_public_cancel_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """按 symbol 批量撤挂单只在公开 cancel 边界记一次 CANCEL_ORDER。"""
    from threading import Event

    from axile.executor.termination import ExecutionTerminationController

    guard = _build_guard({"cancel_order": {"per_day": 1}})
    executor = _build_executor(guard)
    session = ExecutionSession(owner=executor, symbol="SHSE.600000")
    execution_report_calls: list[str] = []
    cancel_calls: list[list[dict[str, str]]] = []
    cancel_event = Event()
    cancel_event.set()
    executor.set_termination_controller(
        ExecutionTerminationController(
            cancel_event=cancel_event,
            reason_provider=lambda: "manual stop",
            mode_provider=lambda: "cancel_pending",
        )
    )

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_unfinished_orders",
        lambda **_kwargs: [
            {
                "account_id": "gm-account",
                "order_id": "1001",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 100,
                "price": 12.3,
                "status": 1,
                "created_at": datetime(2026, 3, 22, 9, 30, 0),
            }
        ],
    )
    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_execution_reports",
        lambda **_kwargs: execution_report_calls.append("called") or [],
    )
    monkeypatch.setattr(
        gm_api_bridge_module,
        "order_cancel",
        lambda *, wait_cancel_orders: cancel_calls.append(wait_cancel_orders),
    )

    with pytest.raises(ExecutionTerminated) as exc_info:
        session.handle_termination_checkpoint()

    assert exc_info.value.cancel_failed_order_ids == []
    assert execution_report_calls == []
    assert cancel_calls == [[{"cl_ord_id": "gm-cl-1", "account_id": "gm-account"}]]

    _, events = guard.flush_records()
    assert [event.operation for event in events] == [
        "query_order",
        "cancel_order",
    ]
    assert all(event.decision == AccountControlDecision.ALLOWED for event in events)


def test_base_executor_termination_cancel_pending_no_longer_cancels_inside_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AbstractExecutor terminate 检查点只 ACK+raise，不再在执行器内批量撤单。"""
    from threading import Event

    from axile.executor.termination import ExecutionTerminated, ExecutionTerminationController

    guard = _build_guard({"cancel_order": {"per_day": 1}})
    executor = _build_executor(guard)
    cancel_calls: list[list[dict[str, str]]] = []
    cancel_event = Event()
    cancel_event.set()
    executor.set_termination_controller(
        ExecutionTerminationController(
            cancel_event=cancel_event,
            reason_provider=lambda: "manual stop",
            mode_provider=lambda: "cancel_pending",
        )
    )

    monkeypatch.setattr(
        gm_api_bridge_module,
        "order_cancel",
        lambda *, wait_cancel_orders: cancel_calls.append(wait_cancel_orders),
    )

    with pytest.raises(ExecutionTerminated) as exc_info:
        executor.handle_termination_checkpoint("SHSE.600000")

    assert exc_info.value.cancel_failed_order_ids == []
    assert cancel_calls == []

    _, events = guard.flush_records()
    assert events == []


def test_query_trade_records_returns_unified_trade_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """GM 内部成交 helper 应直接返回统一成交记录。"""
    executor = _build_executor(_build_guard({}))
    created_at = datetime(2026, 3, 22, 9, 30, 0)

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_execution_reports",
        lambda **_kwargs: [
            {
                "account_id": "gm-account",
                "exec_id": "exec-1",
                "cl_ord_id": "gm-cl-1",
                "order_id": "exchange-1",
                "symbol": "SHSE.600000",
                "volume": 100,
                "price": 12.3,
                "created_at": created_at,
            }
        ],
    )

    trades = executor._query_trade_records()

    assert len(trades) == 1
    assert trades[0].symbol == "SHSE.600000"
    assert trades[0].order_id == "gm-cl-1"
    assert trades[0].extra["account_id"] == "gm-account"
    assert trades[0].extra["exchange_order_id"] == "exchange-1"


def test_query_unfinished_order_records_returns_unified_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """GM unfinished-order helper 应直接返回统一订单。"""
    executor = _build_executor(_build_guard({}))
    created_at = datetime(2026, 3, 22, 9, 30, 0)

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_unfinished_orders",
        lambda **_kwargs: [
            {
                "account_id": "gm-account",
                "order_id": "exchange-1",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 100,
                "price": 12.3,
                "status": 1,
                "created_at": created_at,
            }
        ],
    )

    orders = executor._query_unfinished_order_records()

    assert len(orders) == 1
    assert orders[0].order_id == "gm-cl-1"
    assert orders[0].symbol == "SHSE.600000"
    assert orders[0].extra["account_id"] == "gm-account"
    assert orders[0].extra["exchange_order_id"] == "exchange-1"


def test_query_order_records_returns_unified_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """GM all-orders helper 应直接返回统一订单。"""
    executor = _build_executor(_build_guard({}))
    created_at = datetime(2026, 3, 22, 9, 30, 0)

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_orders",
        lambda **_kwargs: [
            {
                "account_id": "gm-account",
                "order_id": "exchange-1",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 100,
                "price": 12.3,
                "status": 1,
                "created_at": created_at,
            }
        ],
    )

    orders = executor._query_order_records()

    assert len(orders) == 1
    assert orders[0].order_id == "gm-cl-1"
    assert orders[0].symbol == "SHSE.600000"
    assert orders[0].extra["account_id"] == "gm-account"
    assert orders[0].extra["exchange_order_id"] == "exchange-1"

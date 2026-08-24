"""GM 执行器与通用执行器语义对齐测试。"""

from __future__ import annotations

import inspect
import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace
from typing import Any, get_args, get_type_hints

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.utils.order_tracker import OrderTracker
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder


def _install_gm_stubs() -> None:
    gm_module = sys.modules.setdefault("gm", ModuleType("gm"))
    api_module = sys.modules.setdefault("gm.api", ModuleType("gm.api"))
    csdk_module = sys.modules.setdefault("gm.csdk", ModuleType("gm.csdk"))
    c_sdk_module = sys.modules.setdefault("gm.csdk.c_sdk", ModuleType("gm.csdk.c_sdk"))
    model_module = sys.modules.setdefault("gm.model", ModuleType("gm.model"))
    storage_module = sys.modules.setdefault("gm.model.storage", ModuleType("gm.model.storage"))
    pb_module = sys.modules.setdefault("gm.pb", ModuleType("gm.pb"))
    account_pb2_module = sys.modules.setdefault("gm.pb.account_pb2", ModuleType("gm.pb.account_pb2"))
    tradegw_pb2_module = sys.modules.setdefault(
        "gm.pb.tradegw_service_pb2",
        ModuleType("gm.pb.tradegw_service_pb2"),
    )

    api_module.MODE_LIVE = 1
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
    api_module.run = lambda **_kwargs: None
    api_module.set_account_id = lambda *_args, **_kwargs: None
    api_module.set_serv_addr = lambda *_args, **_kwargs: None
    api_module.set_token = lambda *_args, **_kwargs: None
    api_module.subscribe = lambda *_args, **_kwargs: None
    api_module.timer = lambda *_args, **_kwargs: {"timer_id": 10001, "status": 0}
    api_module.timer_stop = lambda *_args, **_kwargs: True

    c_sdk_module.c_status_fail = lambda *_args, **_kwargs: False
    c_sdk_module.py_gmi_get_account_status = lambda *_args, **_kwargs: (0, None)
    c_sdk_module.TickLikeDict2 = type("TickLikeDict2", (), {})

    class DictLikeAccountStatus(dict[str, Any]):
        pass

    class DictLikeExecRpt(dict[str, Any]):
        pass

    class DictLikeOrder(dict[str, Any]):
        pass

    class Context:
        pass

    class AccountStatuses:
        data: list[object] = []

        def ParseFromString(self, _result: bytes) -> None:
            return None

    class GetAccountStatusesReq:
        def __init__(self) -> None:
            self.account_ids: list[str] = []

        def SerializeToString(self) -> bytes:
            return b""

    account_pb2_module.AccountStatuses = AccountStatuses
    tradegw_pb2_module.GetAccountStatusesReq = GetAccountStatusesReq

    gm_module.api = api_module
    gm_module.csdk = csdk_module
    gm_module.model = model_module
    gm_module.pb = pb_module
    csdk_module.c_sdk = c_sdk_module
    model_module.DictLikeAccountStatus = DictLikeAccountStatus
    model_module.DictLikeExecRpt = DictLikeExecRpt
    model_module.DictLikeOrder = DictLikeOrder
    model_module.storage = storage_module
    storage_module.Context = Context
    pb_module.account_pb2 = account_pb2_module
    pb_module.tradegw_service_pb2 = tradegw_pb2_module


_install_gm_stubs()

from axile.executor.gm import common as gm_common_module
from axile.executor.gm import gm_execute as gm_execute_module
from axile.executor.gm.core import api_bridge as gm_api_bridge_module
from axile.executor.gm.core import gm_strategy as gm_strategy_module
from axile.executor.gm.core import strategy_bridge as gm_strategy_bridge_module
from axile.executor.gm.gm_execute import GMExecutor


def _build_executor() -> GMExecutor:
    executor = GMExecutor.__new__(GMExecutor)
    executor.account_id = "gm-account"
    executor.logger = SimpleNamespace(
        info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None
    )
    executor._callback_dispatcher = object()
    executor._strategy_bridge = None
    executor._callback_monitoring = False
    executor._gm_config = None
    executor._subscribe_symbols = []
    executor._execution_order_ids = set()
    executor._fetch_execution_reports = lambda: []  # type: ignore[attr-defined]
    executor._fetch_orders = lambda: []  # type: ignore[attr-defined]
    executor._fetch_unfinished_orders = lambda: []  # type: ignore[attr-defined]
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


def test_convert_gm_order_to_unified_uses_client_order_id_as_unified_order_id() -> None:
    """GM UnifiedOrder.order_id 应对齐为可撤可追踪的 cl_ord_id。"""
    order = gm_execute_module.convert_gm_order_to_unified(
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
    )

    assert order.order_id == "gm-cl-1"
    assert order.extra["cl_ord_id"] == "gm-cl-1"
    assert order.extra["exchange_order_id"] == "1001"


def test_convert_gm_order_to_unified_accepts_order_only() -> None:
    """GM 订单转换器应保持纯订单接口，不再接受成交列表。"""
    assert tuple(inspect.signature(gm_execute_module.convert_gm_order_to_unified).parameters) == ("order",)


def test_gm_execute_reexports_common_helpers() -> None:
    """GM 执行器模块中的转换/状态辅助应来自独立 common 模块。"""
    assert gm_execute_module.from_gm_price is gm_common_module.from_gm_price
    assert gm_execute_module.convert_gm_trade_to_trade_record is gm_common_module.convert_gm_trade_to_trade_record
    assert gm_execute_module.convert_gm_order_to_unified is gm_common_module.convert_gm_order_to_unified


def test_gm_strategy_reuses_common_trade_id_builder() -> None:
    """GM callback bridge 也应直接复用 common 模块里的 trade_id builder。"""
    assert gm_strategy_module._build_gm_trade_id is gm_common_module._build_gm_trade_id


def test_from_gm_price_keeps_top5_levels_and_raw_tick() -> None:
    """GM 通用 tick 转换应保留五档盘口与 raw_data。"""
    tick = {
        "symbol": "SHSE.600000",
        "price": 12.34,
        "bid_price": [12.33, 12.32],
        "ask_price": [12.35],
        "bid_volume": [1000, 900],
        "ask_volume": [1100],
        "volume": 88,
        "timestamp": 1_711_111_111_000,
        "dt": "2026-03-28T09:30:00",
    }

    price = gm_common_module.from_gm_price(tick)

    assert price.symbol == "600000.SH"
    assert price.bid_price == 12.33
    assert price.bid_price_2 == 12.32
    assert price.bid_price_3 == 0.0
    assert price.ask_price == 12.35
    assert price.ask_price_2 == 0.0
    assert price.bid_volume == 1000.0
    assert price.bid_volume_2 == 900.0
    assert price.ask_volume == 1100.0
    assert price.ask_volume_2 == 0.0
    assert price.volume == 88.0
    assert price.timestamp == 1_711_111_111_000
    assert price.update_time == "2026-03-28T09:30:00"
    assert price.extra["channel_type"] == TradeChannel.GM
    assert price.extra["raw_data"] == tick


def test_callback_strategy_tick_conversion_preserves_levels_without_raw_data() -> None:
    """GM callback tick 转换应沿用共享 builder，但不额外挂 raw_data。"""
    tick = SimpleNamespace(
        symbol="SHSE.600000",
        price=12.34,
        last_volume=66,
        created_at=datetime(2026, 3, 28, 9, 30, 0, 123000),
        quotes=[
            SimpleNamespace(bid_p=12.33, ask_p=12.35, bid_v=1000, ask_v=1100),
            SimpleNamespace(bid_p=12.32, ask_p=12.36, bid_v=900, ask_v=1200),
            SimpleNamespace(bid_p=0, ask_p=0, bid_v=0, ask_v=0),
        ],
    )

    price = gm_strategy_module._convert_tick_to_unified(tick)

    assert price.symbol == "600000.SH"
    assert price.bid_price == 12.33
    assert price.bid_price_2 == 12.32
    assert price.bid_price_3 == 0.0
    assert price.ask_price == 12.35
    assert price.ask_price_2 == 12.36
    assert price.ask_price_3 == 0.0
    assert price.bid_volume == 1000.0
    assert price.bid_volume_2 == 900.0
    assert price.ask_volume == 1100.0
    assert price.ask_volume_2 == 1200.0
    assert price.volume == 66.0
    assert price.timestamp == int(tick.created_at.timestamp() * 1000)
    assert price.update_time == "2026-03-28 09:30:00.123"
    assert price.extra == {"channel_type": TradeChannel.GM, "gm_symbol": "SHSE.600000"}


def test_gm_executor_and_strategy_share_same_sdk_bridge_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """GM 执行器通过 strategy bridge 调用，strategy runtime 再统一分发 SDK 请求。"""
    from axile.executor.gm.core.api_bridge import CurrentRequest, GetCashRequest, GMApiBridge

    executor = _build_executor()
    executor._gm_config = SimpleNamespace(account_id="gm-account")
    bridge_call_args: list[tuple[object, float]] = []
    strategy_dispatch_requests: list[object] = []

    class _FakeBridge:
        def call(self, request: object, *, timeout: float) -> dict[str, Any]:
            bridge_call_args.append((request, timeout))
            return {"request": request, "timeout": timeout}

    def fake_execute_request(cls: type[GMApiBridge], request: object) -> dict[str, Any]:
        strategy_dispatch_requests.append(request)
        return {"request": request}

    monkeypatch.setattr(
        executor,
        "_ensure_strategy_bridge",
        lambda *, timeout=30.0, subscribe_symbols=None: _FakeBridge(),
    )
    monkeypatch.setattr(
        GMApiBridge,
        "execute_request",
        classmethod(fake_execute_request),
    )

    executor_request = GetCashRequest(account_id="gm-account")
    strategy_request = CurrentRequest(symbols=["SHSE.600000"])

    executor_result = GMExecutor._call_bridge(executor, executor_request, timeout=12.0)
    strategy_result = gm_strategy_module._dispatch_bridge_request(
        strategy_request,
    )

    assert executor_result == {
        "request": executor_request,
        "timeout": 12.0,
    }
    assert strategy_result == {
        "request": strategy_request,
    }
    assert bridge_call_args == [(executor_request, 12.0)]
    assert strategy_dispatch_requests == [strategy_request]


def test_gm_bridge_operation_annotations_are_tightened() -> None:
    """GM bridge 请求注解应收敛到统一的类型化 request 别名。"""
    from axile.executor.gm.core import api_bridge as gm_api_bridge_module

    sdk_request_types = {
        gm_api_bridge_module.GetCashRequest,
        gm_api_bridge_module.GetPositionRequest,
        gm_api_bridge_module.CurrentRequest,
        gm_api_bridge_module.GetOrdersRequest,
        gm_api_bridge_module.GetUnfinishedOrdersRequest,
        gm_api_bridge_module.GetExecutionReportsRequest,
        gm_api_bridge_module.OrderCancelRequest,
        gm_api_bridge_module.OrderVolumeRequest,
    }
    bridge_request_types = sdk_request_types | {gm_api_bridge_module.GMSubscribeSymbolsRequest}

    assert set(get_args(gm_api_bridge_module.GMSdkRequest)) == sdk_request_types
    assert set(get_args(gm_api_bridge_module.GMBridgeRequestPayload)) == bridge_request_types
    assert get_type_hints(gm_api_bridge_module.GMApiBridge.execute_request)["request"] == (
        gm_api_bridge_module.GMSdkRequest
    )
    assert get_type_hints(GMExecutor._call_bridge)["request"] == gm_api_bridge_module.GMSdkRequest
    assert get_type_hints(gm_strategy_bridge_module.GMStrategyBridge.call)["request"] == (
        gm_api_bridge_module.GMSdkRequest
    )
    assert get_type_hints(gm_strategy_bridge_module.GMStrategyBridge._submit_request)["request"] == (
        gm_api_bridge_module.GMBridgeRequestPayload
    )
    assert get_type_hints(gm_strategy_module._dispatch_bridge_request)["request"] == (
        gm_api_bridge_module.GMBridgeRequestPayload
    )


def test_gm_api_bridge_dispatch_table_uses_callables() -> None:
    """GM SDK dispatch table 应直接保存可调用对象，而不是方法名字符串。"""
    from axile.executor.gm.core.api_bridge import GMApiBridge

    assert GMApiBridge._SDK_OPERATION_METHODS["get_cash"].__func__ is GMApiBridge.get_cash.__func__
    assert GMApiBridge._SDK_OPERATION_METHODS["get_cash"].__self__ is GMApiBridge
    assert GMApiBridge._SDK_OPERATION_METHODS["order_volume"].__func__ is GMApiBridge.order_volume.__func__
    assert GMApiBridge._SDK_OPERATION_METHODS["order_volume"].__self__ is GMApiBridge
    assert all(callable(method) for method in GMApiBridge._SDK_OPERATION_METHODS.values())


def test_order_cancel_request_serializes_typed_cancel_targets() -> None:
    """撤单请求应使用类型化 cancel target，而不是裸 dict 列表。"""
    from axile.executor.gm.core.api_bridge import GMCancelOrderTarget, OrderCancelRequest

    request = OrderCancelRequest(
        wait_cancel_orders=[
            GMCancelOrderTarget(cl_ord_id="gm-cl-1", account_id="gm-account"),
        ]
    )

    assert request.as_kwargs() == {
        "wait_cancel_orders": [
            {"cl_ord_id": "gm-cl-1", "account_id": "gm-account"},
        ]
    }


def test_order_volume_request_serializes_channel_enums_to_raw_ints() -> None:
    """下单请求可使用渠道枚举，但发给 SDK 时必须落回原始 int。"""
    from axile.executor.gm.core.api_bridge import GMOrderKind, GMOrderSide, GMPositionEffect, OrderVolumeRequest

    request = OrderVolumeRequest(
        symbol="SHSE.600000",
        volume=100,
        side=GMOrderSide.BUY,
        order_type=GMOrderKind.LIMIT,
        position_effect=GMPositionEffect.OPEN,
        price=12.3,
        account="gm-account",
    )

    kwargs = request.as_kwargs()

    assert kwargs["side"] == gm_execute_module.GMOrderSide.BUY
    assert type(kwargs["side"]) is int
    assert kwargs["order_type"] == gm_execute_module.GMOrderKind.LIMIT
    assert type(kwargs["order_type"]) is int
    assert kwargs["position_effect"] == gm_execute_module.GMPositionEffect.OPEN
    assert type(kwargs["position_effect"]) is int


def test_get_pending_orders_returns_only_current_symbol_orders(monkeypatch: Any) -> None:
    """挂单查询应只返回当前 symbol 的 GM 订单。"""
    executor = _build_executor()

    monkeypatch.setattr(gm_api_bridge_module, "get_execution_reports", lambda: [])
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
            },
            {
                "account_id": "gm-account",
                "order_id": "1002",
                "cl_ord_id": "gm-cl-2",
                "symbol": "SZSE.000001",
                "side": gm_execute_module.GMOrderSide.BUY,
                "order_type": gm_execute_module.GMOrderKind.LIMIT,
                "volume": 100,
                "price": 10.5,
                "status": 1,
                "created_at": datetime(2026, 3, 22, 9, 31, 0),
            },
        ],
    )

    orders = executor.get_pending_orders("SZSE.000001")

    assert [order.order_id for order in orders] == ["gm-cl-2"]


def test_get_pending_orders_stays_in_order_domain(monkeypatch: Any) -> None:
    """GM 挂单查询只返回订单域快照，不应顺手抓 execution reports 回填成交。"""
    executor = _build_executor()
    execution_report_calls: list[str] = []

    monkeypatch.setattr(
        executor,
        "_query_trade_records",
        lambda account_id=None: execution_report_calls.append("trades") or [],
    )
    monkeypatch.setattr(
        executor,
        "_query_unfinished_order_records",
        lambda account_id=None: [
            gm_execute_module.convert_gm_order_to_unified(
                {
                    "account_id": "gm-account",
                    "order_id": "1001",
                    "cl_ord_id": "gm-cl-1",
                    "symbol": "SHSE.600000",
                    "side": gm_execute_module.GMOrderSide.BUY,
                    "order_type": gm_execute_module.GMOrderKind.LIMIT,
                    "volume": 100,
                    "price": 12.3,
                    "status": 2,
                    "created_at": datetime(2026, 3, 22, 9, 30, 0),
                }
            )
        ],
    )

    orders = executor.get_pending_orders("SHSE.600000")

    assert len(orders) == 1
    assert orders[0].order_id == "gm-cl-1"
    assert orders[0].filled_volume == 0
    assert orders[0].remaining_volume == 100
    assert execution_report_calls == []


def test_get_pending_orders_with_none_returns_all_account_pending_orders(monkeypatch: Any) -> None:
    """GM get_pending_orders(None) 应返回账户下全部未完成委托。"""
    executor = _build_executor()

    monkeypatch.setattr(
        executor,
        "_query_trade_records",
        lambda account_id=None: [],
    )
    monkeypatch.setattr(
        executor,
        "_query_unfinished_order_records",
        lambda account_id=None: [
            gm_execute_module.convert_gm_order_to_unified(
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
            ),
            gm_execute_module.convert_gm_order_to_unified(
                {
                    "account_id": "gm-account",
                    "order_id": "1002",
                    "cl_ord_id": "gm-cl-2",
                    "symbol": "SZSE.000001",
                    "side": gm_execute_module.GMOrderSide.BUY,
                    "order_type": gm_execute_module.GMOrderKind.LIMIT,
                    "volume": 100,
                    "price": 10.5,
                    "status": 1,
                    "created_at": datetime(2026, 3, 22, 9, 31, 0),
                }
            ),
        ],
    )

    orders = executor.get_pending_orders(None)

    assert [order.order_id for order in orders] == ["gm-cl-1", "gm-cl-2"]


def test_place_order_returns_submitted_order_without_execution_tracking(monkeypatch: Any) -> None:
    """GM 下单直接返回 submitted order，不再维护 execution-order 集合。"""
    executor = _build_executor()

    monkeypatch.setattr(
        gm_api_bridge_module,
        "order_volume",
        lambda **_kwargs: [{"cl_ord_id": "gm-cl-9"}],
    )

    order = executor.place_order(
        symbol="SHSE.600000",
        direction=gm_execute_module.OrderDirection.BUY,
        order_type=gm_execute_module.OrderType.LIMIT,
        volume=100,
        price=12.3,
    )

    assert order.order_id == "gm-cl-9"
    assert order.status == OrderStatus.SUBMITTED
    assert order.extra["cl_ord_id"] == "gm-cl-9"
    assert order.extra["exchange_order_id"] is None


def test_place_order_passes_gm_market_order_type_for_market_orders(monkeypatch: Any) -> None:
    """GM MARKET 下单应映射到 GM 的市价委托类型。"""
    executor = _build_executor()
    order_volume_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        gm_api_bridge_module,
        "order_volume",
        lambda **kwargs: order_volume_calls.append(kwargs) or [{"cl_ord_id": "gm-cl-market"}],
    )

    order = executor.place_order(
        symbol="SHSE.600000",
        direction=gm_execute_module.OrderDirection.BUY,
        order_type=gm_execute_module.OrderType.MARKET,
        volume=100,
        price=0,
    )

    assert order.order_type == gm_execute_module.OrderType.MARKET
    assert order.status == OrderStatus.SUBMITTED
    assert order_volume_calls[0]["order_type"] == gm_execute_module.GMOrderKind.MARKET
    assert order_volume_calls[0]["price"] == 0


def test_place_order_casts_volume_to_int_for_gm_sdk(monkeypatch: Any) -> None:
    """GM 下单传给 SDK 的 volume 应是 int，而不是统一层 float。"""
    executor = _build_executor()
    order_volume_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_position",
        lambda **_kwargs: [
            {
                "symbol": "SHSE.588000",
                "side": 1,
                "volume": 75300,
                "available": 75300,
            }
        ],
    )
    monkeypatch.setattr(
        gm_api_bridge_module,
        "order_volume",
        lambda **kwargs: order_volume_calls.append(kwargs) or [{"cl_ord_id": "gm-cl-int-volume"}],
    )

    order = executor.place_order(
        symbol="SHSE.588000",
        direction=gm_execute_module.OrderDirection.SELL,
        order_type=gm_execute_module.OrderType.LIMIT,
        volume=75300.0,
        price=1.33,
    )

    assert order.order_id == "gm-cl-int-volume"
    assert order.status == OrderStatus.SUBMITTED
    assert order_volume_calls[0]["volume"] == 75300
    assert isinstance(order_volume_calls[0]["volume"], int)


def test_place_order_fails_fast_when_sell_close_exceeds_available_long(monkeypatch: Any) -> None:
    """GM A股卖出超过可平仓数量时，应在本地下单前直接失败。"""
    executor = _build_executor()
    order_volume_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        gm_api_bridge_module,
        "get_position",
        lambda **_kwargs: [
            {
                "symbol": "SHSE.588000",
                "side": 1,
                "volume": 100,
                "available": 0,
            }
        ],
    )
    monkeypatch.setattr(
        gm_api_bridge_module,
        "order_volume",
        lambda **kwargs: order_volume_calls.append(kwargs) or [{"cl_ord_id": "gm-cl-invalid-sell"}],
    )

    with pytest.raises(ValueError, match="GM A股账户不支持空仓卖平或超出可平数量"):
        executor.place_order(
            symbol="SHSE.588000",
            direction=gm_execute_module.OrderDirection.SELL,
            order_type=gm_execute_module.OrderType.LIMIT,
            volume=100.0,
            price=1.33,
        )

    assert order_volume_calls == []


def test_callback_strategy_uses_client_order_id_as_unified_order_id() -> None:
    """GM callback 桥接生成的 UnifiedOrder 也应复用 cl_ord_id。"""
    order = gm_strategy_module._convert_order_to_unified(
        SimpleNamespace(
            order_id="1001",
            cl_ord_id="gm-cl-1",
            symbol="SHSE.600000",
            side=gm_execute_module.GMOrderSide.BUY,
            order_type=gm_execute_module.GMOrderKind.LIMIT,
            volume=100,
            price=12.3,
            status=1,
            created_at=datetime(2026, 3, 22, 9, 30, 0),
        )
    )

    assert order.order_id == "gm-cl-1"
    assert order.extra["cl_ord_id"] == "gm-cl-1"
    assert order.extra["exchange_order_id"] == "1001"


def test_callback_strategy_trade_conversion_preserves_order_link_fields() -> None:
    """GM callback 桥接生成的 TradeRecord 应保留可关联订单的主键字段。"""
    trade = gm_strategy_module._convert_execrpt_to_trade(
        SimpleNamespace(
            exec_id="exec-1",
            order_id="1001",
            cl_ord_id="gm-cl-1",
            symbol="SHSE.600000",
            volume=40,
            price=12.3,
            created_at=datetime(2026, 3, 22, 9, 30, 5),
        )
    )

    assert trade.trade_id == "exec-1"
    assert trade.extra["cl_ord_id"] == "gm-cl-1"
    assert trade.extra["exchange_order_id"] == "1001"
    assert trade.extra["symbol"] == "SHSE.600000"


def test_gm_trade_conversion_uses_distinct_fallback_trade_ids_without_exec_id() -> None:
    """GM 在缺少 exec_id 时，不能把同一委托的多笔成交压成同一个 trade_id。"""
    first_trade = gm_execute_module.convert_gm_trade_to_trade_record(
        {
            "order_id": "1001",
            "cl_ord_id": "gm-cl-1",
            "symbol": "SHSE.600000",
            "volume": 40,
            "price": 12.3,
            "created_at": datetime(2026, 3, 24, 9, 0, 0),
        }
    )
    second_trade = gm_execute_module.convert_gm_trade_to_trade_record(
        {
            "order_id": "1001",
            "cl_ord_id": "gm-cl-1",
            "symbol": "SHSE.600000",
            "volume": 20,
            "price": 12.4,
            "created_at": datetime(2026, 3, 24, 9, 0, 1),
        }
    )
    callback_trade = gm_strategy_module._convert_execrpt_to_trade(
        SimpleNamespace(
            order_id="1001",
            cl_ord_id="gm-cl-1",
            symbol="SHSE.600000",
            volume=20,
            price=12.4,
            created_at=datetime(2026, 3, 24, 9, 0, 1),
        )
    )

    assert first_trade.trade_id != second_trade.trade_id
    assert second_trade.trade_id == callback_trade.trade_id


def test_order_tracker_accumulates_multiple_gm_trades_without_exec_id() -> None:
    """GM 多笔无 exec_id 成交回报也应全部累计进 tracked order。"""

    class _Logger:
        def info(self, *_args: object, **_kwargs: object) -> None:
            return None

        def warning(self, *_args: object, **_kwargs: object) -> None:
            return None

        def error(self, *_args: object, **_kwargs: object) -> None:
            return None

        def debug(self, *_args: object, **_kwargs: object) -> None:
            return None

    class _TrackerExecutor:
        logger = _Logger()

        def get_pending_orders(self) -> list[UnifiedOrder]:
            return []

        def handle_termination_checkpoint(self) -> None:
            return None

        def get_tick_size(self) -> float | None:
            return None

        def cancel_order(self, order_id: str) -> bool:
            _ = order_id
            return True

        def place_order(self, *args: object, **kwargs: object) -> UnifiedOrder:
            _ = (args, kwargs)
            raise NotImplementedError

        def emit_audit_event(self, **kwargs: object) -> bool:
            _ = kwargs
            return False

        def is_termination_requested(self) -> bool:
            return False

        def get_termination_mode(self) -> str | None:
            return None

    tracker = OrderTracker(executor=_TrackerExecutor())
    tracker.add_order(
        UnifiedOrder(
            order_id="gm-cl-1",
            symbol="SHSE.600000",
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=100.0,
            price=12.3,
            status=OrderStatus.PARTIALLY_FILLED,
        )
    )

    tracker.on_trade_record(
        gm_execute_module.convert_gm_trade_to_trade_record(
            {
                "order_id": "1001",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "volume": 40,
                "price": 12.3,
                "created_at": datetime(2026, 3, 24, 9, 0, 0),
            }
        )
    )
    tracker.on_trade_record(
        gm_execute_module.convert_gm_trade_to_trade_record(
            {
                "order_id": "1001",
                "cl_ord_id": "gm-cl-1",
                "symbol": "SHSE.600000",
                "volume": 20,
                "price": 12.4,
                "created_at": datetime(2026, 3, 24, 9, 0, 1),
            }
        )
    )

    tracked_order = tracker.pending_orders["gm-cl-1"]
    assert tracked_order.filled_volume == 0.0
    assert tracked_order.remaining_volume == 100.0
    tracked_trades = tracker.get_order_trades("gm-cl-1")
    assert len(tracked_trades) == 2
    assert {trade.trade_volume for trade in tracked_trades} == {40.0, 20.0}
    assert len({trade.trade_id for trade in tracked_trades}) == 2


def test_convert_gm_order_to_unified_preserves_account_id() -> None:
    order = gm_execute_module.convert_gm_order_to_unified(
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
            "created_at": datetime(2026, 3, 25, 9, 30, 0),
        }
    )

    assert order.extra["account_id"] == "gm-account"


def test_convert_gm_trade_to_trade_record_preserves_account_id() -> None:
    trade = gm_execute_module.convert_gm_trade_to_trade_record(
        {
            "account_id": "gm-account",
            "order_id": "1001",
            "cl_ord_id": "gm-cl-1",
            "symbol": "SHSE.600000",
            "volume": 20,
            "price": 12.3,
            "created_at": datetime(2026, 3, 25, 9, 30, 1),
        }
    )

    assert trade.extra["account_id"] == "gm-account"


def test_callback_strategy_order_conversion_preserves_account_id() -> None:
    order = gm_strategy_module._convert_order_to_unified(
        SimpleNamespace(
            account_id="gm-account",
            order_id="1001",
            cl_ord_id="gm-cl-1",
            symbol="SHSE.600000",
            side=gm_execute_module.GMOrderSide.BUY,
            order_type=gm_execute_module.GMOrderKind.LIMIT,
            volume=100,
            price=12.3,
            status=1,
            created_at=datetime(2026, 3, 25, 9, 30, 0),
        )
    )

    assert order.extra["account_id"] == "gm-account"


def test_callback_strategy_trade_conversion_preserves_account_id() -> None:
    trade = gm_strategy_module._convert_execrpt_to_trade(
        SimpleNamespace(
            account_id="gm-account",
            order_id="1001",
            cl_ord_id="gm-cl-1",
            symbol="SHSE.600000",
            volume=20,
            price=12.3,
            created_at=datetime(2026, 3, 25, 9, 30, 1),
        )
    )

    assert trade.extra["account_id"] == "gm-account"

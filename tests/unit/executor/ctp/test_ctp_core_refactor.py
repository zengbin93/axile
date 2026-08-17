"""CTP 核心 API 收口与重连辅助逻辑的离线测试。"""

from __future__ import annotations

import importlib
import sys
import tempfile
import threading
import types
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.presets import resolve_account_control_policy
from axile.executor.account_control.registry import (
    get_default_account_control_registry,
    reset_default_account_control_registry_for_tests,
)
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder


class _AdvancingClock:
    def __init__(self, start_time: datetime) -> None:
        self._current = start_time
        self.sleep_calls: list[float] = []

    def now(self) -> datetime:
        return self._current

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self._current += timedelta(seconds=seconds)


class _ClockStub:
    def __init__(self, current_time: float = 0.0, sleep_calls: list[float] | None = None) -> None:
        self._current_time = current_time
        self._sleep_calls = sleep_calls

    def time(self) -> float:
        return self._current_time

    def sleep(self, seconds: float) -> None:
        self._current_time += seconds
        if self._sleep_calls is not None:
            self._sleep_calls.append(seconds)

    def event_wait(self, event: threading.Event, timeout: float) -> bool:
        waited = event.wait(timeout=min(timeout, 0.01))
        if not waited and timeout > 0:
            self._current_time += timeout
        return waited


def _build_ctp_guard(clock: _AdvancingClock) -> AccountControlGuard:
    return AccountControlGuard(
        account_id=7,
        execution_id="exec-ctp-core",
        channel=TradeChannel.CTP,
        policy=resolve_account_control_policy("ctp"),
        baseline=AccountControlCounterSnapshot(),
        clock=clock.now,
        sleep=clock.sleep,
    )


def _import_ctp_core_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, object, object]:
    class _Placeholder:
        pass

    stub_modules = {
        "sqlalchemy": types.SimpleNamespace(JSON=object(), Boolean=object()),
        "sqlmodel": types.SimpleNamespace(SQLModel=object()),
        "axile.executor.algorithms.utils": types.SimpleNamespace(
            ChaseConfig=_Placeholder,
            OrderTracker=_Placeholder,
            create_empty_result=lambda *_args, **_kwargs: None,
            determine_order_price=lambda *_args, **_kwargs: None,
            get_default_clock=lambda: _ClockStub(),
        ),
    }

    # CtpTrader 已拆分为 ``trader`` 包；除主模块外，子模块（_constants /
    # connection / instruments / positions / orders / risk / market_data /
    # options / _main）的 ``@controlled_operation`` 装饰器必须在每次重置
    # registry 之后随重新 import 而再次执行，因此一并清掉。
    for module_name in [
        "axile.executor.ctp.core.market_data",
        "axile.executor.ctp.core.trader",
        "axile.executor.ctp.core.trader._constants",
        "axile.executor.ctp.core.trader._main",
        "axile.executor.ctp.core.trader.connection",
        "axile.executor.ctp.core.trader.instruments",
        "axile.executor.ctp.core.trader.positions",
        "axile.executor.ctp.core.trader.orders",
        "axile.executor.ctp.core.trader.risk",
        "axile.executor.ctp.core.trader.options",
        "axile.executor.ctp.core.trader.market_data",
        "axile.executor.ctp.core.reconnect",
        "axile",
    ]:
        sys.modules.pop(module_name, None)

    for module_name, module_stub in stub_modules.items():
        monkeypatch.setitem(sys.modules, module_name, module_stub)

    market_data_module = importlib.import_module("axile.executor.ctp.core.market_data")
    trader_module = importlib.import_module("axile.executor.ctp.core.trader")
    reconnect_module = importlib.import_module("axile.executor.ctp.core.reconnect")
    return market_data_module.CtpMarketData, trader_module.CtpTrader, reconnect_module


def test_ctp_core_package_eagerly_exports_public_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """CTP core 包应在导入时直接绑定公开符号，而不是依赖模块级懒加载。"""
    core_module_name = "axile.executor.ctp.core"
    export_modules = {
        "axile.executor.ctp.core.trader": types.ModuleType("axile.executor.ctp.core.trader"),
        "axile.executor.ctp.core.market_data": types.ModuleType("axile.executor.ctp.core.market_data"),
        "axile.executor.ctp.core.reconnect": types.ModuleType("axile.executor.ctp.core.reconnect"),
        "axile.executor.ctp.core.error_handler": types.ModuleType("axile.executor.ctp.core.error_handler"),
    }

    export_modules["axile.executor.ctp.core.trader"].CtpTrader = object()
    export_modules["axile.executor.ctp.core.market_data"].CtpMarketData = object()
    export_modules["axile.executor.ctp.core.reconnect"].ReconnectController = object()
    export_modules["axile.executor.ctp.core.reconnect"].ReconnectPolicy = object()
    export_modules["axile.executor.ctp.core.error_handler"].handle_ctp_error = object()

    sys.modules.pop(core_module_name, None)
    for module_name, module in export_modules.items():
        monkeypatch.setitem(sys.modules, module_name, module)

    core_module = importlib.import_module(core_module_name)

    assert core_module.CtpTrader is export_modules["axile.executor.ctp.core.trader"].CtpTrader
    assert core_module.CtpMarketData is export_modules["axile.executor.ctp.core.market_data"].CtpMarketData
    assert core_module.ReconnectController is export_modules["axile.executor.ctp.core.reconnect"].ReconnectController
    assert core_module.ReconnectPolicy is export_modules["axile.executor.ctp.core.reconnect"].ReconnectPolicy
    assert core_module.handle_ctp_error is export_modules["axile.executor.ctp.core.error_handler"].handle_ctp_error
    assert "CtpTrader" in core_module.__dict__
    assert "CtpMarketData" in core_module.__dict__
    assert "__getattr__" not in core_module.__dict__


def _import_ctp_objects_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    class _Placeholder:
        pass

    stub_modules = {
        "sqlalchemy": types.SimpleNamespace(JSON=object(), Boolean=object()),
        "sqlmodel": types.SimpleNamespace(SQLModel=object()),
        "axile.executor.algorithms.utils": types.SimpleNamespace(
            ChaseConfig=_Placeholder,
            OrderTracker=_Placeholder,
            create_empty_result=lambda *_args, **_kwargs: None,
            determine_order_price=lambda *_args, **_kwargs: None,
            get_default_clock=lambda: _ClockStub(),
        ),
    }

    for module_name in [
        "axile.executor.ctp.core.objects",
        "axile",
    ]:
        sys.modules.pop(module_name, None)

    for module_name, module_stub in stub_modules.items():
        monkeypatch.setitem(sys.modules, module_name, module_stub)

    return importlib.import_module("axile.executor.ctp.core.objects")


def _make_trader(monkeypatch: pytest.MonkeyPatch) -> tuple[object, types.ModuleType, MagicMock]:
    _, CtpTrader, _ = _import_ctp_core_modules(monkeypatch)
    trader_module = importlib.import_module("axile.executor.ctp.core.trader")
    logger = MagicMock()
    stub_api = types.SimpleNamespace(Release=lambda: None)

    def _create_trader_api(_self: object, _host: str) -> object:
        return stub_api

    monkeypatch.setattr(CtpTrader, "_create_trader_api", _create_trader_api)

    trader = CtpTrader(
        host="tcp://td",
        broker="9999",
        user="000001",
        password="secret",
        appid="app-id",
        authcode="auth-code",
        logger=logger,
    )
    return trader, trader_module, logger


def test_trader_remote_operations_register_into_shared_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """CTP trader 远端请求应注册为共享 group 下的 operation。"""
    reset_default_account_control_registry_for_tests()
    _ = _import_ctp_core_modules(monkeypatch)
    registry = get_default_account_control_registry()
    expected_operations = {
        "query_account",
        "query_positions",
        "query_instruments",
        "query_option_instruments",
        "query_orders",
        "query_settlement_info",
        "insert_order",
    }

    assert expected_operations <= set(registry.operations)
    assert "ctp_td_global" in registry.groups
    assert all(registry.require_operation(key).groups == frozenset({"ctp_td_global"}) for key in expected_operations)


def test_trader_query_account_and_query_positions_share_one_group_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """不同查询方法之间的节流应来自共享 group，而不是本地 flow controller。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.api = types.SimpleNamespace(
        ReqQryTradingAccount=lambda _req, _request_id: 0,
        ReqQryInvestorPosition=lambda _req, _request_id: 0,
    )
    # query_account / query_positions 现在位于 ``trader/positions.py`` 中，
    # 该模块直接 ``from ._constants import _wait_or_raise``，所以要 patch 子模块。
    positions_module = importlib.import_module("axile.executor.ctp.core.trader.positions")
    monkeypatch.setattr(positions_module, "_wait_or_raise", lambda *_args, **_kwargs: None)

    clock = _AdvancingClock(datetime(2026, 3, 25, 9, 31, 15))
    trader.set_account_control_guard(_build_ctp_guard(clock))

    trader.query_account()
    trader.query_positions()

    assert sum(clock.sleep_calls) == pytest.approx(1.5)
    assert len(clock.sleep_calls) == 15


def test_trader_cancel_all_orders_no_longer_uses_local_flow_control_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """批量撤单不应再依赖 trader 内部的 sleep 节流。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    orders = {
        "1": SimpleNamespace(
            InstrumentID="rb2605",
            OrderSysID="1",
            OrderRef="1",
            ExchangeID="SHFE",
            OrderStatus=trader_module.OrderStatusType.NO_TRADE_QUEUEING,
        ),
        "2": SimpleNamespace(
            InstrumentID="ag2605",
            OrderSysID="2",
            OrderRef="2",
            ExchangeID="SHFE",
            OrderStatus=trader_module.OrderStatusType.NO_TRADE_QUEUEING,
        ),
    }
    sleep_calls: list[float] = []

    monkeypatch.setattr(trader, "query_orders", lambda instrument_id="", timeout=30.0: orders)
    monkeypatch.setattr(trader, "cancel_order", lambda order, method="auto": True)
    # ``cancel_all_orders`` 现在位于 ``trader/orders.py``，但实际不再调用
    # ``get_default_clock``。保留 patch 是为了断言 ``sleep_calls == []``。
    orders_module = importlib.import_module("axile.executor.ctp.core.trader.orders")
    monkeypatch.setattr(orders_module, "get_default_clock", lambda: _ClockStub(sleep_calls=sleep_calls))

    result = trader.cancel_all_orders(use_flow_control=True)

    assert result["cancel_success"] == 2
    assert sleep_calls == []


def test_ctp_objects_import_emits_no_pydantic_deprecation_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """CTP 对象模型应使用现代 Pydantic 配置声明。"""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        objects_module = _import_ctp_objects_module(monkeypatch)
        model = objects_module.BaseCtpModel()

    assert model.model_config.get("validate_by_name") is True
    assert not any("class-based `config`" in str(item.message).lower() for item in captured)


def test_market_data_connect_raises_typed_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """行情连接超时时应抛出专门的超时异常。"""
    CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)
    market_data_module = importlib.import_module("axile.executor.ctp.core.market_data")

    client = CtpMarketData("tcp://md")
    setattr(client, "_create_md_api", lambda: types.SimpleNamespace(Init=lambda: None))
    client.reconnect_config.connection_timeout = 0.01

    with pytest.raises(market_data_module.CtpMarketDataTimeoutError):
        client.connect()


def test_market_data_wait_raises_typed_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """请求停止事件后，行情等待应快速中止。"""
    _CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)
    market_data_module = importlib.import_module("axile.executor.ctp.core.market_data")

    stop_event = threading.Event()
    timer = threading.Timer(0.01, stop_event.set)
    timer.start()

    try:
        with pytest.raises(market_data_module.CtpMarketDataCancelledError):
            market_data_module._wait_or_raise(
                threading.Event(),
                1.0,
                "行情等待超时",
                stop_event=stop_event,
            )
    finally:
        timer.cancel()


def test_market_data_subscribe_raises_cancellation_when_stop_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """行情订阅被取消时，应显式暴露取消，而不是看起来像正常返回。"""
    CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)
    market_data_module = importlib.import_module("axile.executor.ctp.core.market_data")

    client = CtpMarketData("tcp://md")
    client.api = types.SimpleNamespace(SubscribeMarketData=lambda _symbols, _count: 0)

    timer = threading.Timer(0.01, client.request_stop)
    timer.start()

    try:
        with pytest.raises(market_data_module.CtpMarketDataCancelledError):
            client.subscribe(["rb2505"])
    finally:
        timer.cancel()


def test_market_data_dispatches_remaining_callbacks_after_callback_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """单个失败回调应被隔离，不影响后续回调继续收到 tick。"""
    CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)

    client = CtpMarketData("tcp://md")
    received: list[object] = []

    def _failing_callback(_price: object) -> None:
        raise RuntimeError("boom")

    def _collect_callback(price: object) -> None:
        received.append(price)

    client.register_price_callback(_failing_callback)
    client.register_price_callback(_collect_callback)

    quote = types.SimpleNamespace(
        InstrumentID="rb2505",
        LastPrice=4500.0,
        BidPrice1=4499.0,
        AskPrice1=4501.0,
        BidVolume1=10,
        AskVolume1=12,
        Volume=100,
        UpdateTime="09:30:00",
        UpdateMillisec=500,
    )
    print("Dispatching quote with one failing callback...")
    client.OnRtnDepthMarketData(quote)

    assert len(received) == 1
    assert getattr(received[0], "symbol") == "rb2505"


def test_market_data_summaries_are_sorted_by_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    """行情摘要输出应保持确定性，便于下游消费。"""
    CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)

    client = CtpMarketData("tcp://md")
    client.quotes = {
        "rb2505": types.SimpleNamespace(
            InstrumentID="rb2505",
            LastPrice=4500.0,
            PreSettlementPrice=4400.0,
            Volume=100,
            Turnover=100000.0,
            OpenInterest=50,
            BidPrice1=4499.0,
            BidVolume1=10,
            AskPrice1=4501.0,
            AskVolume1=12,
            UpdateTime="09:30:00",
            UpdateMillisec=100,
            TradingDay="20260319",
        ),
        "ag2505": types.SimpleNamespace(
            InstrumentID="ag2505",
            LastPrice=7000.0,
            PreSettlementPrice=6900.0,
            Volume=80,
            Turnover=80000.0,
            OpenInterest=30,
            BidPrice1=6999.0,
            BidVolume1=8,
            AskPrice1=7001.0,
            AskVolume1=9,
            UpdateTime="09:31:00",
            UpdateMillisec=200,
            TradingDay="20260319",
        ),
    }

    summaries = client.get_all_quotes_summary()

    assert [summary["instrument_id"] for summary in summaries] == ["ag2505", "rb2505"]


def test_trader_flow_path_is_scoped_by_account(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """交易 flow 目录应按账户隔离，避免所有账户共享同一路径。"""
    _, CtpTrader, _ = _import_ctp_core_modules(monkeypatch)
    trader_module = importlib.import_module("axile.executor.ctp.core.trader")
    captured: dict[str, str] = {}

    class _StubTraderApi:
        def RegisterSpi(self, _spi: object) -> None:
            return None

        def RegisterFront(self, _host: str) -> None:
            return None

        def SubscribePrivateTopic(self, _resume_type: int) -> None:
            return None

        def SubscribePublicTopic(self, _resume_type: int) -> None:
            return None

    temp_cleaner_module = importlib.import_module("axile.executor.ctp.utils.temp_cleaner")

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(temp_cleaner_module, "register_temp_path", lambda _path: None)
    monkeypatch.setattr(trader_module.ctp_compat, "ensure_openctp_loaded", lambda: None)
    monkeypatch.setattr(trader_module.ctp_compat, "create_trader_spi_proxy", lambda _client: object())

    def _create_trader_api(flow_path: str) -> object:
        captured["flow_path"] = flow_path
        return _StubTraderApi()

    monkeypatch.setattr(
        trader_module.CThostFtdcTraderApi,
        "CreateFtdcTraderApi",
        _create_trader_api,
    )

    _ = CtpTrader(
        host="tcp://td",
        broker="9999",
        user="000001",
        password="secret",
        appid="app-id",
        authcode="auth-code",
    )

    assert captured["flow_path"] == str(tmp_path / "ctp_flow" / "9999_000001" / "trader")


def test_market_data_flow_path_is_scoped_by_account(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """行情 flow 目录应按账户隔离，避免所有账户共享同一路径。"""
    CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)
    market_data_module = importlib.import_module("axile.executor.ctp.core.market_data")
    captured: dict[str, str] = {}

    class _StubMdApi:
        def RegisterFront(self, _front: str) -> None:
            return None

        def RegisterSpi(self, _spi: object) -> None:
            return None

    temp_cleaner_module = importlib.import_module("axile.executor.ctp.utils.temp_cleaner")

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(temp_cleaner_module, "register_temp_path", lambda _path: None)
    monkeypatch.setattr(market_data_module.ctp_compat, "ensure_openctp_loaded", lambda: None)
    monkeypatch.setattr(market_data_module.ctp_compat, "create_md_spi_proxy", lambda _client: object())

    def _create_md_api(flow_path: str) -> object:
        captured["flow_path"] = flow_path
        return _StubMdApi()

    monkeypatch.setattr(
        market_data_module.ctp_compat.CThostFtdcMdApi,
        "CreateFtdcMdApi",
        _create_md_api,
    )

    client = CtpMarketData("tcp://md", account_id="9999_000001")
    _ = client._create_md_api()

    assert captured["flow_path"] == str(tmp_path / "ctp_flow" / "9999_000001" / "md")


def test_reconnect_policy_uses_fixed_interval_without_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """禁用退避时，重连辅助逻辑应保持固定间隔。"""
    _, _, reconnect_module = _import_ctp_core_modules(monkeypatch)
    ReconnectController = reconnect_module.ReconnectController
    ReconnectPolicy = reconnect_module.ReconnectPolicy

    controller = ReconnectController(
        name="test",
        policy=ReconnectPolicy(
            reconnect_interval=3.0,
            exponential_backoff=False,
            max_reconnect_interval=30.0,
        ),
        attempt_reconnect=lambda: False,
    )

    assert controller.compute_interval(1) == 3.0
    assert controller.compute_interval(4) == 3.0


def test_reconnect_policy_caps_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """重连辅助逻辑应将指数退避限制在配置的最大间隔内。"""
    _, _, reconnect_module = _import_ctp_core_modules(monkeypatch)
    ReconnectController = reconnect_module.ReconnectController
    ReconnectPolicy = reconnect_module.ReconnectPolicy

    controller = ReconnectController(
        name="test",
        policy=ReconnectPolicy(
            reconnect_interval=2.0,
            exponential_backoff=True,
            max_reconnect_interval=5.0,
        ),
        attempt_reconnect=lambda: False,
    )

    assert controller.compute_interval(1) == 2.0
    assert controller.compute_interval(2) == 4.0
    assert controller.compute_interval(3) == 5.0


def test_reconnect_controller_runs_success_callback_after_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """重连成功时，重连辅助逻辑应调用成功回调。"""
    _, _, reconnect_module = _import_ctp_core_modules(monkeypatch)
    ReconnectController = reconnect_module.ReconnectController
    ReconnectPolicy = reconnect_module.ReconnectPolicy

    success_calls: list[str] = []
    attempt_calls: list[str] = []

    controller = ReconnectController(
        name="test",
        policy=ReconnectPolicy(reconnect_interval=0.01, max_reconnect_attempts=3),
        attempt_reconnect=lambda: attempt_calls.append("attempt") is None or True,
        on_reconnect_success=lambda: success_calls.append("success"),
    )

    controller.start()
    controller.join(timeout=1.0)

    assert attempt_calls == ["attempt"]
    assert success_calls == ["success"]
    assert controller.attempts == 0
    assert not controller.is_running


def test_reconnect_controller_stop_sets_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """停止重连辅助逻辑时，应标记停止事件并终止工作线程。"""
    _, _, reconnect_module = _import_ctp_core_modules(monkeypatch)
    ReconnectController = reconnect_module.ReconnectController
    ReconnectPolicy = reconnect_module.ReconnectPolicy

    release_gate = threading.Event()

    def _attempt() -> bool:
        release_gate.wait(0.2)
        return False

    controller = ReconnectController(
        name="test",
        policy=ReconnectPolicy(reconnect_interval=0.01, max_reconnect_attempts=2),
        attempt_reconnect=_attempt,
    )

    controller.start()
    controller.stop(timeout=1.0)
    release_gate.set()

    assert controller.stop_event.is_set()
    assert not controller.is_running


def test_market_data_close_unregisters_spi_before_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭行情客户端时，应先解绑 SPI，再释放原生 API。"""
    CtpMarketData, _, _ = _import_ctp_core_modules(monkeypatch)

    client = CtpMarketData("tcp://md")
    api = MagicMock()
    client.api = api
    client.reconnect = MagicMock()
    client.reconnect.is_running = False

    client.close()

    register_index = api.mock_calls.index(call.RegisterSpi(None))
    release_index = api.mock_calls.index(call.Release())

    assert register_index < release_index


def test_trader_close_unregisters_spi_before_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭交易客户端时，应先解绑 SPI，再释放原生 API。"""
    trader, _, _ = _make_trader(monkeypatch)
    api = MagicMock()
    trader.api = api
    trader.reconnect = MagicMock()
    trader.reconnect.is_running = False

    trader.close()

    register_index = api.mock_calls.index(call.RegisterSpi(None))
    release_index = api.mock_calls.index(call.Release())

    assert register_index < release_index


def test_trader_query_account_passes_stop_event_to_waiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """交易账户查询应使用共享停止事件，以支持可取消等待。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    captured: dict[str, object] = {}

    def _fake_wait_or_raise(
        event: threading.Event,
        timeout: float,
        message: str,
        stop_event: threading.Event | None = None,
        poll_interval: float = 0.1,
    ) -> None:
        captured["event"] = event
        captured["timeout"] = timeout
        captured["message"] = message
        captured["stop_event"] = stop_event
        captured["poll_interval"] = poll_interval
        raise trader_module.CtpCancelledError("cancelled")

    positions_module = importlib.import_module("axile.executor.ctp.core.trader.positions")
    monkeypatch.setattr(positions_module, "_wait_or_raise", _fake_wait_or_raise)
    trader.api = types.SimpleNamespace(ReqQryTradingAccount=lambda _req, _request_id: 0)

    with pytest.raises(trader_module.CtpCancelledError):
        trader.query_account()

    assert captured["stop_event"] is trader.stop_event


def test_trader_query_account_raises_cancellation_when_stop_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """清理请求触发停止后，交易查询应及时中止。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.api = types.SimpleNamespace(ReqQryTradingAccount=lambda _req, _request_id: 0)

    timer = threading.Timer(0.01, trader.request_stop)
    timer.start()

    try:
        with pytest.raises(trader_module.CtpCancelledError):
            trader.query_account()
    finally:
        timer.cancel()


def test_trader_close_reuses_market_data_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """交易客户端关闭时，应将行情清理委托给 md 客户端自身处理。"""
    trader, _, _ = _make_trader(monkeypatch)
    trader.md_client = MagicMock()
    trader.md_connected = True
    trader.reconnect = MagicMock()
    trader.reconnect.is_running = False

    trader.close()

    trader.md_client.close.assert_called_once_with()
    assert trader.md_connected is False


def test_trader_refresh_order_statuses_syncs_unified_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """刷新查询得到的 CTP 订单时，应同步更新跟踪中的 UnifiedOrder 状态。"""
    trader, _, _ = _make_trader(monkeypatch)
    trader._dispatch_order_callback = MagicMock()

    tracked_order = MagicMock()
    tracked_order.order_id = "1"
    tracked_order.status = "待成交"
    tracked_order.filled_volume = 0.0
    tracked_order.avg_price = 0.0
    tracked_order.extra = {"order_ref": "1", "front_id": 1, "session_id": 2}
    tracked_order.update_timestamp = 0.0
    trader._unified_orders = {"1": tracked_order}

    refreshed_unified = MagicMock()
    refreshed_unified.status = "已成交"
    refreshed_unified.filled_volume = 1.0
    refreshed_unified.avg_price = 100.0
    refreshed_unified.extra = {"status_msg": "全部成交"}

    refreshed_order_model = SimpleNamespace(
        OrderSysID="100001",
        OrderRef="1",
        FrontID=1,
        SessionID=2,
        VolumeTraded=1,
        to_unified=lambda: refreshed_unified,
    )

    monkeypatch.setattr(
        trader,
        "query_orders",
        lambda instrument_id="", timeout=10.0: {"100001": refreshed_order_model},
    )

    refreshed_orders = trader.refresh_order_statuses(timeout=10.0)

    assert refreshed_orders == [tracked_order]
    assert tracked_order.order_id == "100001"
    assert tracked_order.status == "已成交"
    assert tracked_order.filled_volume == 1.0
    assert tracked_order.avg_price == 100.0
    assert tracked_order.extra["status_msg"] == "全部成交"
    trader._dispatch_order_callback.assert_called_once_with(tracked_order)


def test_trader_refresh_order_statuses_does_not_backfill_order_from_trade_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """刷新订单状态只使用订单域信息，不应再从本地成交缓存回填 order 聚合字段。"""
    trader, _, _ = _make_trader(monkeypatch)
    trader._dispatch_order_callback = MagicMock()

    tracked_order = UnifiedOrder(
        order_id="1",
        symbol="rb2505",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1.0,
        price=100.0,
        status="待成交",
        filled_volume=0.0,
        avg_price=0.0,
        extra={"order_ref": "1", "front_id": 1, "session_id": 2},
    )
    trader._unified_orders = {"1": tracked_order}
    trader.trades = {
        "trade-1": SimpleNamespace(
            to_unified_trade=lambda: TradeRecord.create(
                trade_id="trade-1",
                symbol="rb2505",
                order_id="100001",
                trade_time="2026-03-25T09:30:00",
                trade_volume=1.0,
                trade_price=100.0,
            )
        )
    }

    refreshed_unified = MagicMock()
    refreshed_unified.status = "待成交"
    refreshed_unified.filled_volume = 0.0
    refreshed_unified.avg_price = 0.0
    refreshed_unified.extra = {"status_msg": "挂单中"}

    refreshed_order_model = SimpleNamespace(
        OrderSysID="100001",
        OrderRef="1",
        FrontID=1,
        SessionID=2,
        VolumeTraded=0,
        to_unified=lambda: refreshed_unified,
    )

    monkeypatch.setattr(
        trader,
        "query_orders",
        lambda instrument_id="", timeout=10.0: {"100001": refreshed_order_model},
    )

    refreshed_orders = trader.refresh_order_statuses(timeout=10.0)

    assert refreshed_orders == [tracked_order]
    assert tracked_order.filled_volume == 0.0
    assert tracked_order.avg_price == 0.0


def test_trader_connection_info_includes_reconnect_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接信息应暴露重连状态与备用服务器容量。"""
    trader, trader_module, _ = _make_trader(monkeypatch)

    trader.connection_status = trader_module.ConnectionStatus.READY
    trader.connected = True
    trader.authenticated = True
    trader.logged_in = True
    trader.settlement_confirmed = True
    trader.reconnect.attempts = 2
    trader.reconnect.last_disconnect_time = 123.45
    trader.current_server_index = 1
    trader.reconnect_config.backup_servers = ["tcp://backup-a", "tcp://backup-b"]

    info = trader.get_connection_info()

    assert info == {
        "connection_status": "ready",
        "connected": True,
        "authenticated": True,
        "logged_in": True,
        "settlement_confirmed": True,
        "reconnect_attempts": 2,
        "last_disconnect_time": 123.45,
        "auto_reconnect_enabled": True,
        "current_server_index": 1,
        "available_servers": 3,
    }


def test_trader_update_reconnect_config_ignores_unknown_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """更新重连配置时，只应应用已知的策略字段。"""
    trader, _, logger = _make_trader(monkeypatch)

    trader.update_reconnect_config(reconnect_interval=2.5, unknown_flag=True)

    assert trader.reconnect_config.reconnect_interval == 2.5
    logger.info.assert_any_call("✅ 重连配置已更新：reconnect_interval = 2.5")
    logger.warning.assert_any_call("⚠️  未知的重连配置项：unknown_flag")


def test_trader_operation_frequency_prunes_stale_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """频率检查应先清理过期操作，再执行限制判断。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.risk_config.max_queries_per_minute = 1
    trader.operation_history.append(trader_module.OperationCounter(timestamp=39.0, operation_type="query"))

    monkeypatch.setattr(
        importlib.import_module("axile.executor.ctp.core.trader.risk"),
        "get_default_clock",
        lambda: _ClockStub(current_time=100.0),
    )

    allowed, message = trader._check_operation_frequency("query")

    assert allowed is True
    assert message == "频率检查通过"
    assert list(trader.operation_history) == []


def test_trader_operation_frequency_blocks_when_threshold_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    """达到每分钟阈值后，频率检查应拒绝新的请求。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.risk_config.max_orders_per_minute = 1
    trader.operation_history.append(trader_module.OperationCounter(timestamp=90.0, operation_type="order"))

    monkeypatch.setattr(
        importlib.import_module("axile.executor.ctp.core.trader.risk"),
        "get_default_clock",
        lambda: _ClockStub(current_time=100.0),
    )

    allowed, message = trader._check_operation_frequency("order")

    assert allowed is False
    assert "委托频率超限" in message


def test_trader_order_volume_rejects_open_position_over_total_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """当开仓单会使总风险暴露超过配置上限时，应判定失败。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.risk_config.max_total_position = 5
    monkeypatch.setattr(
        trader,
        "get_position_info",
        lambda _instrument_id: {"long_position": 2, "short_position": 2},
    )

    allowed, message = trader._check_order_volume("rb2505", 2, trader_module.THOST_FTDC_OF_Open)

    assert allowed is False
    assert "总持仓将超限" in message


def test_trader_order_volume_skips_total_position_check_for_close_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """平仓单不应被开仓总量限制所阻挡。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.risk_config.max_total_position = 1
    monkeypatch.setattr(
        trader,
        "get_position_info",
        lambda _instrument_id: {"long_position": 10, "short_position": 10},
    )

    allowed, message = trader._check_order_volume("rb2505", 1, trader_module.THOST_FTDC_OF_Close)

    assert allowed is True
    assert message == "数量检查通过"


def test_trader_order_rate_rejects_requests_inside_minimum_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """下单频率检查应强制执行连续两次下单之间的最小间隔。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.risk_config.min_order_interval = 0.5
    trader.last_order_time = 99.8

    monkeypatch.setattr(
        importlib.import_module("axile.executor.ctp.core.trader.risk"),
        "get_default_clock",
        lambda: _ClockStub(current_time=100.0),
    )

    allowed, message = trader._check_order_rate()

    assert allowed is False
    assert "报单间隔过短" in message


def test_trader_order_rate_rejects_too_many_recent_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """下单频率检查应拒绝超过每秒阈值的突发请求。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    trader.risk_config.max_orders_per_second = 2
    trader.operation_history.extend(
        [
            trader_module.OperationCounter(timestamp=99.9, operation_type="order"),
            trader_module.OperationCounter(timestamp=99.6, operation_type="order"),
        ]
    )

    monkeypatch.setattr(
        importlib.import_module("axile.executor.ctp.core.trader.risk"),
        "get_default_clock",
        lambda: _ClockStub(current_time=100.0),
    )

    allowed, message = trader._check_order_rate()

    assert allowed is False
    assert "报单速率过快" in message


def test_trader_order_price_rejects_price_above_upper_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """价格检查应阻止高于合约涨停上限的委托。"""
    trader, _, _ = _make_trader(monkeypatch)
    trader.instruments["rb2505"] = types.SimpleNamespace(
        PriceTick=1.0,
        UpperLimitPrice=100.0,
        LowerLimitPrice=80.0,
        PreClosePrice=90.0,
        PreSettlementPrice=0.0,
    )

    allowed, message = trader._check_order_price("rb2505", 101.0)

    assert allowed is False
    assert "超过涨停价" in message


def test_trader_order_price_rejects_large_reference_deviation(monkeypatch: pytest.MonkeyPatch) -> None:
    """价格检查应拒绝偏离参考价过远的委托。"""
    trader, _, _ = _make_trader(monkeypatch)
    trader.risk_config.max_price_deviation = 0.05
    trader.instruments["rb2505"] = types.SimpleNamespace(
        PriceTick=1.0,
        UpperLimitPrice=120.0,
        LowerLimitPrice=80.0,
        PreClosePrice=90.0,
        PreSettlementPrice=0.0,
    )

    allowed, message = trader._check_order_price("rb2505", 96.0)

    assert allowed is False
    assert "价格偏离过大" in message


def test_trader_should_drop_historical_terminal_gfd_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """历史终态的 GFD 订单应从缓存订单快照中过滤掉。"""
    trader, trader_module, _ = _make_trader(monkeypatch)
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    order = types.SimpleNamespace(
        OrderStatus=trader_module.OrderStatusType.CANCELED,
        InsertDate=yesterday,
        TimeCondition="3",
    )

    assert trader._should_keep_order(order) is False


def test_trader_positions_summary_aggregates_and_sorts_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    """持仓摘要应按合约聚合，并保持稳定顺序。"""
    trader, _, _ = _make_trader(monkeypatch)
    trader.positions = {
        "rb_long": types.SimpleNamespace(
            InstrumentID="rb2505",
            ExchangeID="SHFE",
            PosiDirection="2",
            PositionDate="1",
            Position=3,
            YdPosition=1,
            TodayPosition=2,
            PositionProfit=10.0,
            PositionCost=100.0,
            UseMargin=20.0,
            SettlementPrice=4400.0,
            HedgeFlag="1",
        ),
        "rb_short": types.SimpleNamespace(
            InstrumentID="rb2505",
            ExchangeID="SHFE",
            PosiDirection="3",
            PositionDate="2",
            Position=1,
            YdPosition=1,
            TodayPosition=0,
            PositionProfit=-1.0,
            PositionCost=30.0,
            UseMargin=5.0,
            SettlementPrice=4400.0,
            HedgeFlag="1",
        ),
        "ag_long": types.SimpleNamespace(
            InstrumentID="ag2505",
            ExchangeID="SHFE",
            PosiDirection="2",
            PositionDate="1",
            Position=2,
            YdPosition=0,
            TodayPosition=2,
            PositionProfit=8.0,
            PositionCost=60.0,
            UseMargin=12.0,
            SettlementPrice=6900.0,
            HedgeFlag="1",
        ),
    }
    monkeypatch.setattr(trader, "query_positions", lambda _instrument_id="": trader.positions)

    summary = trader.get_positions_summary()

    assert [item["instrument_id"] for item in summary] == ["ag2505", "rb2505"]
    rb_summary = summary[1]
    assert rb_summary["long_position"] == 3
    assert rb_summary["short_position"] == 1
    assert rb_summary["net_position"] == 2
    assert rb_summary["total_position_profit"] == 9.0
    assert rb_summary["total_use_margin"] == 25.0
    assert len(rb_summary["details"]) == 2


def test_investor_position_log_calculates_net_from_long_minus_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """投资者持仓完成日志应根据多头减空头计算净持仓。"""
    trader, _, logger = _make_trader(monkeypatch)

    long_position = types.SimpleNamespace(
        InstrumentID="m2605",
        PosiDirection="2",
        PositionDate="1",
        Position=22,
    )
    short_position = types.SimpleNamespace(
        InstrumentID="m2605",
        PosiDirection="3",
        PositionDate="2",
        Position=7,
    )

    trader.OnRspQryInvestorPosition(long_position, None, 0, False)
    trader.OnRspQryInvestorPosition(short_position, None, 0, True)

    info_messages = [call.args[0] for call in logger.info.call_args_list]

    expected_message = "合约 m2605: 多头22手, 空头7手, 净持仓15手"

    assert any(expected_message in message for message in info_messages)


def test_investor_position_callback_splits_combination_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """组合持仓响应应拆成两条单腿持仓，并跳过原始组合记录。"""
    trader, trader_module, logger = _make_trader(monkeypatch)

    positions_module = importlib.import_module("axile.executor.ctp.core.trader.positions")
    monkeypatch.setattr(
        positions_module,
        "split_combination_position",
        lambda _position: [
            {"InstrumentID": "a2605", "PosiDirection": "2", "Position": 5, "PositionDate": "1"},
            {"InstrumentID": "m2605", "PosiDirection": "3", "Position": 5, "PositionDate": "1"},
        ],
    )
    monkeypatch.setattr(
        positions_module,
        "get_combination_info",
        lambda _instrument_id: {"description": "大商所跨品种套利"},
    )
    monkeypatch.setattr(
        positions_module.CtpConverter,
        "position_to_model",
        lambda position: types.SimpleNamespace(**position.__dict__),
    )

    combination_position = types.SimpleNamespace(
        InstrumentID="SPC a2605&m2605",
        PosiDirection="2",
        PositionDate="1",
        Position=5,
        YdPosition=2,
        TodayPosition=3,
        PositionProfit=8.0,
        UseMargin=12.0,
    )

    trader.OnRspQryInvestorPosition(combination_position, None, 0, False)

    assert sorted(trader.positions) == ["a2605_2_1", "m2605_3_1"]
    assert trader.positions["a2605_2_1"].InstrumentID == "a2605"
    assert trader.positions["a2605_2_1"].PosiDirection == "2"
    assert trader.positions["m2605_3_1"].InstrumentID == "m2605"
    assert trader.positions["m2605_3_1"].PosiDirection == "3"
    assert set(trader.positions) == {"a2605_2_1", "m2605_3_1"}

    info_messages = [call.args[0] for call in logger.info.call_args_list]
    assert any("拆分组合持仓: SPC a2605&m2605" in message for message in info_messages)


# ---- P0-1：query_option_instruments 期权过滤路由 ---------------------------------


def test_should_keep_instrument_drops_options_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """常规 query_instruments 路径下，期权（ProductClass=='2'）必须被过滤掉。"""
    trader, _trader_module, _ = _make_trader(monkeypatch)
    option = types.SimpleNamespace(
        InstrumentID="m2510-C-3000",
        ProductClass="2",
        InstrumentStatus="2",
    )
    assert trader._should_keep_instrument(option) is False


def test_should_keep_instrument_keeps_options_when_include_options_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """通过 include_options=True 显式开关，期权可以通过过滤。"""
    trader, _trader_module, _ = _make_trader(monkeypatch)
    option = types.SimpleNamespace(
        InstrumentID="m2510-C-3000",
        ProductClass="2",
        InstrumentStatus="2",
    )
    assert trader._should_keep_instrument(option, include_options=True) is True


def test_on_rsp_qry_instrument_keeps_option_when_option_query_event_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当 _option_query_event_keys 非空时，OnRspQryInstrument 应放期权进 self.instruments。"""
    trader, _trader_module, _ = _make_trader(monkeypatch)
    instruments_module = importlib.import_module("axile.executor.ctp.core.trader.instruments")

    # 直接构造一个期权 InstrumentField stub
    option_payload = types.SimpleNamespace(
        InstrumentID="m2510-C-3000",
        ProductClass="2",
        InstrumentStatus="2",
        UnderlyingInstrID="m2510",
    )

    def _passthrough_to_model(payload: object) -> object:
        # 直接复用 stub 作为模型，便于断言访问字段
        return types.SimpleNamespace(**payload.__dict__)

    monkeypatch.setattr(instruments_module.CtpConverter, "instrument_to_model", _passthrough_to_model)

    # 模拟 query_option_instruments 已设置标记
    event_key = "option_instrument___m2510-C-3000"
    trader.query_events[event_key] = threading.Event()
    trader._option_query_event_keys.add(event_key)

    trader.OnRspQryInstrument(option_payload, None, 0, True)

    assert "m2510-C-3000" in trader.instruments
    assert trader.instruments["m2510-C-3000"].ProductClass == "2"
    # bIsLast 之后批次标记必须被清理
    assert event_key not in trader._option_query_event_keys
    # 事件已 set
    assert trader.query_events[event_key].is_set()


def test_on_rsp_qry_instrument_drops_option_when_no_option_query_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """普通 query_instruments 批次（_option_query_event_keys 为空）下，期权仍被过滤。"""
    trader, _trader_module, _ = _make_trader(monkeypatch)
    instruments_module = importlib.import_module("axile.executor.ctp.core.trader.instruments")

    option_payload = types.SimpleNamespace(
        InstrumentID="m2510-C-3000",
        ProductClass="2",
        InstrumentStatus="2",
    )

    monkeypatch.setattr(
        instruments_module.CtpConverter,
        "instrument_to_model",
        lambda payload: types.SimpleNamespace(**payload.__dict__),
    )

    # 不设置 _option_query_event_keys → 走默认过滤
    trader.OnRspQryInstrument(option_payload, None, 0, True)

    assert "m2510-C-3000" not in trader.instruments


def test_query_option_instruments_round_trip_admits_option_to_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：query_option_instruments → OnRspQryInstrument → self.instruments 含期权。"""
    trader, _trader_module, _ = _make_trader(monkeypatch)
    instruments_module = importlib.import_module("axile.executor.ctp.core.trader.instruments")

    # 让回调推送一条期权数据
    option_payload = types.SimpleNamespace(
        InstrumentID="m2510-C-3000",
        ProductClass="2",
        InstrumentStatus="2",
        UnderlyingInstrID="m2510",
    )

    monkeypatch.setattr(
        instruments_module.CtpConverter,
        "instrument_to_model",
        lambda payload: types.SimpleNamespace(**payload.__dict__),
    )

    def _fake_req_qry_instrument(_req: object, _request_id: int) -> int:
        # 模拟 SDK：立刻在同线程内回调
        trader.OnRspQryInstrument(option_payload, None, 0, True)
        return 0

    trader.api = types.SimpleNamespace(ReqQryInstrument=_fake_req_qry_instrument)

    # 让 _wait_or_raise 立即返回，避免真实等待
    monkeypatch.setattr(instruments_module, "_wait_or_raise", lambda *_args, **_kwargs: None)
    # 跳过频控检查
    monkeypatch.setattr(trader, "_check_operation_frequency", lambda _op: (True, ""))
    monkeypatch.setattr(trader, "_record_operation", lambda _op: None)

    options = trader.query_option_instruments(instrument_id="m2510-C-3000")

    assert "m2510-C-3000" in options
    assert "m2510-C-3000" in trader.instruments
    assert trader.instruments["m2510-C-3000"].ProductClass == "2"
    # 批次标记必须清理
    assert not trader._option_query_event_keys

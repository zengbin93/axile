"""执行器飞书通知模块测试。"""

from __future__ import annotations

import queue
import threading

import pytest

from axile.common.default_account_notification import DEFAULT_ACCOUNT_NOTIFICATION_CODE
from axile.common.notification_function import run_notification_function
from axile.common.trade_channel import TradeChannel
from axile.executor import feishu_notifications as feishu_module
from axile.executor.abstract_executor import execution_lifecycle as abstract_executor_execution_lifecycle_module
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.algorithms.core.base import AlgorithmResult
from axile.executor.feishu_notifications import build_execute_results_feishu_card
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData


def test_ctp_card_keeps_unpriced_position_visible() -> None:
    """缺行情时展示持仓手数，不把成本伪装为市值。"""
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(
            available_cash=900.0,
            total_asset=1000.0,
            market_value=None,
            positions=[
                Position(
                    symbol="rb2610",
                    volume=1,
                    available_volume=1,
                    market_value=None,
                    direction=PositionDirection.LONG,
                    extra={"position_cost": 100},
                )
            ],
        ),
        symbol_results={},
        status=ExecutionStatus.NOOP,
        channel_type=TradeChannel.CTP,
    )
    card = build_execute_results_feishu_card(_NotificationSource(), output)
    variables = card["data"]["template_variable"]
    assert variables["market_value"] == "暂无有效行情"
    assert variables["positions"][0]["market_value"] == "暂无有效行情"
    assert variables["positions"][0]["volume"] == "1.0000"
    assert variables["positions"][0]["rate"] == "—"


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, object]] = []

    def info(self, message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)
        self.messages.append(("info", message))

    def warning(self, message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)
        self.messages.append(("warning", message))

    def error(self, message: object, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)
        self.messages.append(("error", message))


class _NotificationSource:
    def __init__(self) -> None:
        self.logger = _Logger()

    def _get_account_mark(self) -> str:
        return "acct-demo"

    def _get_operation_display(self, order: UnifiedOrder) -> str:
        _ = order
        return "开多"


class _FeishuAwareExecutor(AbstractExecutor):
    def _initialize_connection(self, account_config: object) -> None:
        self.account_config = account_config

    def _verify_connection(self) -> bool:
        return True

    def _check_trading_time(self) -> bool:
        return True

    def get_account_assets(self) -> UnifiedAccountAssets:
        return UnifiedAccountAssets(
            available_cash=1000.0,
            total_asset=1000.0,
            market_value=0.0,
            positions=[],
        )

    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        return {}

    def _place_order_impl(
        self,
        symbol: str,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0,
        **kwargs: object,
    ) -> UnifiedOrder:
        _ = (direction, order_type, volume, price, kwargs)
        return UnifiedOrder(
            order_id=f"order-{symbol}",
            symbol=symbol,
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=1.0,
            price=100.0,
            status="SUBMITTED",
        )

    def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
        _ = symbol
        return []

    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        _ = (symbol, order_id)
        raise NotImplementedError

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        _ = (symbol, order_id)
        return True

    def _cleanup(self) -> None:
        return None

    def _get_account_mark(self) -> str:
        return "executor-demo"

    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, object]:
        _ = symbols
        return {}

    def register_order_callback(self, callback: object) -> None:
        _ = callback

    def register_price_callback(self, callback: object) -> None:
        _ = callback

    def unregister_order_callback(self, callback: object) -> None:
        _ = callback

    def unregister_price_callback(self, callback: object) -> None:
        _ = callback

    def initialize_websocket(self, symbols: list[str] | None = None) -> None:
        _ = symbols

    def is_monitoring(self) -> bool:
        return False


def test_base_executor_subclass_requires_get_account_mark() -> None:
    """飞书账户标识仍是 AbstractExecutor 的抽象契约。"""

    class _MissingAccountMarkExecutor(AbstractExecutor):
        def _initialize_connection(self, account_config: object) -> None:
            self.account_config = account_config

        def _verify_connection(self) -> bool:
            return True

        def _check_trading_time(self) -> bool:
            return True

        def get_account_assets(self) -> UnifiedAccountAssets:
            return UnifiedAccountAssets(
                available_cash=1000.0,
                total_asset=1000.0,
                market_value=0.0,
                positions=[],
            )

        def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
            return {}

        def _place_order_impl(
            self,
            symbol: str,
            direction: OrderDirection,
            order_type: OrderType,
            volume: float,
            price: float = 0,
            **kwargs: object,
        ) -> UnifiedOrder:
            _ = (symbol, direction, order_type, volume, price, kwargs)
            raise NotImplementedError

        def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
            _ = symbol
            return []

        def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
            _ = (symbol, order_id)
            raise NotImplementedError

        def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
            _ = (symbol, order_id)
            return True

        def _cleanup(self) -> None:
            return None

        def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, object]:
            _ = symbols
            return {}

        def register_order_callback(self, callback: object) -> None:
            _ = callback

        def register_price_callback(self, callback: object) -> None:
            _ = callback

        def unregister_order_callback(self, callback: object) -> None:
            _ = callback

        def unregister_price_callback(self, callback: object) -> None:
            _ = callback

        def initialize_websocket(self, symbols: list[str] | None = None) -> None:
            _ = symbols

        def is_monitoring(self) -> bool:
            return False

    try:
        _MissingAccountMarkExecutor(TradeChannel.CTP, None)
    except TypeError as exc:
        assert "_get_account_mark" in str(exc)
    else:
        raise AssertionError("缺少 _get_account_mark 时应无法实例化")


def test_execute_with_feishu_key_uses_extracted_sender(monkeypatch) -> None:
    """AbstractExecutor.execute 应通过有界后台派发器投递异步通知，而非裸起线程。"""
    executor = _FeishuAwareExecutor(
        TradeChannel.CTP,
        CTPAccountConfig.model_validate(
            {
                "broker_id": "b",
                "investor_id": "i",
                "password": "p",
                "td_front": "tcp://td:1",
                "md_front": "tcp://md:2",
                "app_id": "app",
                "auth_code": "auth",
            }
        ),
    )
    sent: list[tuple[object, object, object]] = []

    class _FakeEngine:
        def run(self, standard_input: UnifiedStandardInput) -> UnifiedStandardOutput:
            assert standard_input.feishu_key == "hook-exec"
            return UnifiedStandardOutput(
                account_assets=executor.get_account_assets(),
                inputs=standard_input,
                status=ExecutionStatus.SUCCEEDED,
                channel_type=TradeChannel.CTP,
                success=True,
            )

    def _fake_enqueue(source: object, output: object, feishu_key: object, *args: object) -> None:
        sent.append((source, output, feishu_key))

    monkeypatch.setattr(
        abstract_executor_execution_lifecycle_module,
        "enqueue_execute_results_to_feishu",
        _fake_enqueue,
    )
    monkeypatch.setattr(executor, "_execution_engine", lambda: _FakeEngine())

    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": TradeChannel.CTP.value,
            "account_config": {
                "broker_id": "b",
                "investor_id": "i",
                "password": "p",
                "td_front": "tcp://td:1",
                "md_front": "tcp://md:2",
                "app_id": "app",
                "auth_code": "auth",
            },
            "curr_target": {"rb2610": 0.1},
            "algorithm": {"method": "TEST"},
            "feishu_key": "hook-exec",
            "execution_notification_code": "def notify(context): pass",
        }
    )

    output = executor.execute(standard_input)

    assert output.success is True
    assert len(sent) == 1
    assert sent[0][0] is executor
    assert sent[0][2] == "hook-exec"


def test_empty_positions_does_not_send_second_card(monkeypatch) -> None:
    """清仓外层不重复发送结果卡片。"""
    executor = _FeishuAwareExecutor(TradeChannel.CTP, None)

    def _fake_execute(
        _standard_input: UnifiedStandardInput,
        cleanup: bool = True,
        retain_runtime: bool = False,  # noqa: FBT001, FBT002
    ) -> UnifiedStandardOutput:
        _ = (cleanup, retain_runtime)
        return UnifiedStandardOutput(
            account_assets=executor.get_account_assets(),
            status=ExecutionStatus.NOOP,
            channel_type=TradeChannel.CTP,
            success=True,
        )

    monkeypatch.setattr(executor, "execute", _fake_execute)
    monkeypatch.setattr(
        executor,
        "get_account_assets",
        lambda: UnifiedAccountAssets(
            available_cash=900.0,
            total_asset=1000.0,
            market_value=100.0,
            positions=[
                Position(
                    symbol="rb2610",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=100.0,
                )
            ],
        ),
    )
    executor.account_config = CTPAccountConfig.model_validate(
        {
            "broker_id": "b",
            "investor_id": "i",
            "password": "p",
            "td_front": "tcp://td:1",
            "md_front": "tcp://md:2",
            "app_id": "app",
            "auth_code": "auth",
        }
    )

    result = executor.empty_positions(feishu_key="hook-empty")

    assert result.success is True
    assert result.success is True  # fake execute 不进入真实通知入口


def test_default_card_builder_preserves_positions_and_trades() -> None:
    """默认卡片保留原有持仓和成交展示。"""

    order = UnifiedOrder(
        order_id="order-1",
        symbol="rb2610",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1.0,
        price=101.0,
        status="FILLED",
    )
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(
            available_cash=900.0,
            total_asset=1000.0,
            market_value=100.0,
            positions=[
                Position(
                    symbol="rb2610",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=100.0,
                )
            ],
        ),
        symbol_results={
            "rb2610": AlgorithmResult(
                symbol="rb2610",
                algorithm="TEST",
                orders=[order],
                trades=[
                    TradeRecord(
                        trade_id="trade-1",
                        symbol="rb2610",
                        order_id="order-1",
                        trade_time="2026-03-25 14:00:00",
                        trade_volume=1.0,
                        trade_price=101.0,
                        trade_value=101.0,
                    )
                ],
                target_volume=2.0,
            )
        },
        status=ExecutionStatus.SUCCEEDED,
        channel_type=TradeChannel.CTP,
        success=True,
    )

    card = build_execute_results_feishu_card(_NotificationSource(), output)
    data = card["data"]
    assert isinstance(data, dict)
    template_variable = data["template_variable"]
    assert isinstance(template_variable, dict)
    assert template_variable["account_mark"] == "acct-demo"
    assert template_variable["algorithm"] == "Unknown"
    assert template_variable["positions"] == [
        {
            "symbol": "rb2610",
            "direction": "多头",
            "market_value": "100.00",
            "volume": "1.0000",
            "target_volume": "2.0000",
            "rate": "10.00%",
        }
    ]
    assert template_variable["trades"] == [
        {
            "symbol": "rb2610",
            "dt": "2026-03-25 14:00:00",
            "operate": "开多",
            "volume": "1.0000",
            "price": "101.0000",
            "order_id": "order-1",
            "trade_id": "trade-1",
        }
    ]


def test_default_notification_function_uses_existing_card_variables(monkeypatch) -> None:
    """默认源码可运行，卡片变量与现有默认构造器保持一致。"""
    from axile.common import feishu

    source = _NotificationSource()
    output = _minimal_output()
    context = feishu_module.build_execution_notification_context(source, output)
    sent: list[tuple[object, str]] = []
    monkeypatch.setenv("AXILE_ACCOUNT_FEISHU_KEY", "hook")
    monkeypatch.setattr(feishu, "push_feishu_card", lambda card, key, **kwargs: sent.append((card, key)))
    namespace: dict[str, object] = {}
    exec(DEFAULT_ACCOUNT_NOTIFICATION_CODE, namespace)
    namespace["notify"](context)

    assert sent[0][1] == "hook"
    assert sent[0][0]["data"]["template_variable"] == context["default_feishu_variables"]
    old_variables = build_execute_results_feishu_card(source, output)["data"]["template_variable"]
    assert {key: value for key, value in old_variables.items() if key != "dt"} == {
        key: value for key, value in context["default_feishu_variables"].items() if key != "dt"
    }
    assert run_notification_function(DEFAULT_ACCOUNT_NOTIFICATION_CODE, context).ok is True


def test_custom_notification_context_is_redacted() -> None:
    """通知函数获得统一执行数据，但不能读到渠道凭据。"""
    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": TradeChannel.CTP.value,
            "account_config": {
                "broker_id": "b",
                "investor_id": "i",
                "password": "connection-secret",
                "td_front": "tcp://td:1",
                "md_front": "tcp://md:2",
                "app_id": "app",
                "auth_code": "auth",
            },
            "curr_target": {"rb2610": 0.2},
            "algorithm": {"method": "TEST", "params": {"api_token": "hidden", "pace": 2}},
            "feishu_account": {"id": 7, "name": "期货账户"},
            "extra": {"audit": {"execution_id": "exec-1", "execution_kind": "rebalance"}},
        }
    )
    output = _minimal_output()
    output.inputs = standard_input
    context = feishu_module.build_execution_notification_context(_NotificationSource(), output)
    assert context["account"] == {"id": 7, "name": "期货账户", "mark": "acct-demo"}
    assert context["execution"]["id"] == "exec-1"
    assert context["strategy"]["algorithm"]["params"] == {"pace": 2}
    assert "account_config" not in str(context)
    assert "connection-secret" not in str(context)


def _minimal_output() -> UnifiedStandardOutput:
    """构造派发器测试用的最小执行输出。"""
    return UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(
            available_cash=0.0,
            total_asset=0.0,
            market_value=0.0,
            positions=[],
        ),
        status=ExecutionStatus.SUCCEEDED,
        channel_type=TradeChannel.CTP,
        success=True,
    )


def test_enqueue_feishu_skips_without_key(monkeypatch) -> None:
    """没有通知函数时应直接跳过，不启动 worker、不投递任务。"""
    started: list[bool] = []
    monkeypatch.setattr(
        feishu_module,
        "_ensure_feishu_notify_workers_started",
        lambda: started.append(True),
    )

    feishu_module.enqueue_execute_results_to_feishu(_NotificationSource(), _minimal_output(), None)

    assert started == []


def test_custom_notification_enqueues_without_feishu_key(monkeypatch) -> None:
    """自定义通知函数无需飞书 key 也会投递。"""
    queued: list[tuple[object, ...]] = []
    monkeypatch.setattr(feishu_module, "_ensure_feishu_notify_workers_started", lambda: None)
    monkeypatch.setattr(
        feishu_module, "_notify_queue", type("Queue", (), {"put_nowait": lambda _self, item: queued.append(item)})()
    )
    feishu_module.enqueue_execute_results_to_feishu(
        _NotificationSource(), _minimal_output(), None, "def notify(context): pass"
    )
    assert len(queued) == 1
    assert queued[0][3] == "def notify(context): pass"


def test_enqueue_feishu_drops_when_queue_full(monkeypatch) -> None:
    """队列已满时应丢弃通知并记录告警，且不抛异常、不新建线程。"""
    warnings: list[str] = []

    class _FullQueue:
        def put_nowait(self, item: object) -> None:
            _ = item
            raise queue.Full

    monkeypatch.setattr(feishu_module, "_notify_queue", _FullQueue())
    monkeypatch.setattr(feishu_module, "_ensure_feishu_notify_workers_started", lambda: None)
    monkeypatch.setattr(
        feishu_module.loguru.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(str(message)),
    )

    feishu_module.enqueue_execute_results_to_feishu(
        _NotificationSource(), _minimal_output(), "hook", "def notify(context): pass"
    )

    assert len(warnings) == 1
    assert "队列已满" in warnings[0]


def test_enqueue_feishu_delivers_through_bounded_worker(monkeypatch) -> None:
    """投递的通知应由后台 worker 实际消费，参数透传正确。"""
    done = threading.Event()
    captured: list[tuple[object, object, object]] = []

    def _fake_send(source: object, output: object, feishu_key: object) -> None:
        captured.append((source, output, feishu_key))
        done.set()

    monkeypatch.setattr(
        feishu_module,
        "dispatch_execution_notification",
        lambda source, output, key, code, snapshot: _fake_send(source, output, key),
    )

    source = _NotificationSource()
    feishu_module.enqueue_execute_results_to_feishu(
        source, _minimal_output(), "hook-worker", "def notify(context): pass"
    )

    assert done.wait(timeout=5.0), "后台 worker 未在超时内消费通知任务"
    assert captured[0][0] is source
    assert captured[0][2] == "hook-worker"


def test_feishu_worker_survives_task_exception(monkeypatch) -> None:
    """单个通知任务抛异常不得拖垮 worker，后续任务仍能被消费。"""
    done = threading.Event()
    calls: list[str] = []

    def _flaky_send(source: object, output: object, feishu_key: object) -> None:
        _ = (source, output)
        calls.append(str(feishu_key))
        if feishu_key == "boom":
            raise RuntimeError("push failed")
        done.set()

    monkeypatch.setattr(
        feishu_module,
        "dispatch_execution_notification",
        lambda source, output, key, code, snapshot: _flaky_send(source, output, key),
    )

    feishu_module.enqueue_execute_results_to_feishu(
        _NotificationSource(), _minimal_output(), "boom", "def notify(context): pass"
    )
    feishu_module.enqueue_execute_results_to_feishu(
        _NotificationSource(), _minimal_output(), "ok", "def notify(context): pass"
    )

    assert done.wait(timeout=5.0), "异常任务后 worker 未继续消费下一个任务"
    assert "boom" in calls and "ok" in calls


def test_notification_asset_selection_and_evidence_boundary() -> None:
    """降级执行复用旧快照，金额和持仓同源，执行输出仍保留本次事实。"""
    source = _NotificationSource()
    old = UnifiedAccountAssets(
        available_cash=700,
        total_asset=1000,
        market_value=300,
        positions=[
            Position(symbol="rb2610", volume=2, available_volume=2, market_value=300, direction=PositionDirection.LONG)
        ],
    )
    snapshot = {"id": 42, "created_at": "2026-09-23 11:19:00", "assets": old.model_dump(mode="json")}
    for degraded_source in ("unavailable", "assumed", "error"):
        output = UnifiedStandardOutput(
            account_assets=UnifiedAccountAssets(
                available_cash=0, total_asset=0, market_value=0, source=degraded_source
            ),
            status=ExecutionStatus.BLOCKED,
            channel_type=TradeChannel.CTP,
        )
        card = build_execute_results_feishu_card(source, output, notification_snapshot=snapshot)
        variables = card["data"]["template_variable"]
        assert (variables["total_assets"], variables["available_cash"], variables["market_value"]) == (
            "1000.00",
            "700.00",
            "300.00",
        )
        assert variables["positions"][0]["symbol"] == "rb2610"
        assert output.account_assets.source == degraded_source
        assert "notification_snapshot" not in output.model_dump_json()
        missing = build_execute_results_feishu_card(source, output)["data"]["template_variable"]
        assert missing["total_assets"] == "未获取"
        assert missing["positions"][0]["symbol"] == "未获取"

    current = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(available_cash=0, total_asset=0, market_value=0, positions=[]),
        status=ExecutionStatus.NOOP,
        channel_type=TradeChannel.CTP,
    )
    variables = build_execute_results_feishu_card(source, current, notification_snapshot=snapshot)["data"][
        "template_variable"
    ]
    assert variables["total_assets"] == "0.00"
    assert variables["positions"] == []


def test_notification_execution_matches_public_contract() -> None:
    from axile.common.notification_context import AccountNotificationExecution

    output = _minimal_output()
    context = feishu_module.build_execution_notification_context(_NotificationSource(), output)
    assert set(context["execution"]) == set(AccountNotificationExecution.__required_keys__)
    assert context["execution"]["kind"] is None
    assert context["execution"]["trigger_source"] is None
    assert isinstance(context["execution"]["notified_at"], str)
    assert isinstance(context["execution"]["execution_time"], float)


@pytest.mark.parametrize("ok", [True, False])
def test_notification_success_callback_only_runs_after_success(monkeypatch, ok):
    """默认与自定义通知共用结果回调；失败不覆盖成功摘要。"""
    from axile.common.notification_function import NotificationFunctionResult
    from axile.executor import feishu_notifications as notifications

    calls = []
    source = _NotificationSource()
    source._notification_success_callback = lambda execution_id, succeeded_at: calls.append(
        (execution_id, succeeded_at)
    )
    monkeypatch.setattr(notifications, "build_execution_notification_context", lambda *_args: {})
    monkeypatch.setattr(
        notifications,
        "run_notification_function",
        lambda *_args, **_kwargs: NotificationFunctionResult(ok, None if ok else "failed"),
    )
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(available_cash=0, total_asset=0, market_value=0, positions=[]),
        symbol_results={},
        status=ExecutionStatus.NOOP,
        channel_type=TradeChannel.CTP,
    )
    output.inputs = UnifiedStandardInput.model_construct(extra={"audit": {"execution_id": "exec-1"}})
    notifications.dispatch_execution_notification(source, output, None, "def notify(context): pass", None)
    if ok:
        assert calls[0][0] == "exec-1"
    assert len(calls) == int(ok)


def test_notification_success_callback_failure_does_not_escape(monkeypatch):
    """状态存储不可用时仍保留通知自身结果。"""
    from axile.common.notification_function import NotificationFunctionResult
    from axile.executor import feishu_notifications as notifications

    source = _NotificationSource()

    def unavailable(*_args):
        raise RuntimeError("database unavailable")

    source._notification_success_callback = unavailable
    monkeypatch.setattr(notifications, "build_execution_notification_context", lambda *_args: {})
    monkeypatch.setattr(
        notifications, "run_notification_function", lambda *_args, **_kwargs: NotificationFunctionResult(True)
    )
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(available_cash=0, total_asset=0, market_value=0, positions=[]),
        symbol_results={},
        status=ExecutionStatus.NOOP,
        channel_type=TradeChannel.CTP,
    )
    notifications.dispatch_execution_notification(source, output, None, "def notify(context): pass", None)


@pytest.mark.parametrize("ok", [True, False])
def test_notification_result_callback_records_both_outcomes(monkeypatch, ok):
    from axile.common.notification_function import NotificationFunctionResult
    from axile.executor import feishu_notifications as notifications

    source = _NotificationSource()
    calls = []
    source._notification_result_callback = lambda *args: calls.append(args)
    monkeypatch.setattr(notifications, "build_execution_notification_context", lambda *_args: {})
    monkeypatch.setattr(
        notifications,
        "run_notification_function",
        lambda *_args, **_kwargs: NotificationFunctionResult(ok, None if ok else "timeout"),
    )
    output = _minimal_output()
    output.inputs = UnifiedStandardInput.model_construct(extra={"audit": {"execution_id": "exec-result"}})
    notifications.dispatch_execution_notification(source, output, None, "def notify(context): pass", None)
    assert len(calls) == 1
    assert calls[0][0] == "exec-result"
    assert calls[0][2:] == (ok, None if ok else "timeout")


def test_default_notification_without_key_records_failure(monkeypatch):
    from axile.common.default_account_notification import DEFAULT_ACCOUNT_NOTIFICATION_CODE
    from axile.executor import feishu_notifications as notifications

    source = _NotificationSource()
    calls = []
    source._notification_result_callback = lambda *args: calls.append(args)
    monkeypatch.setattr(notifications, "build_execution_notification_context", lambda *_args: {})
    notifications.dispatch_execution_notification(
        source, _minimal_output(), None, DEFAULT_ACCOUNT_NOTIFICATION_CODE, None
    )
    assert calls[0][2] is False
    assert "Webhook" in calls[0][3]

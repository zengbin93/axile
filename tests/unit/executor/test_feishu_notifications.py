"""执行器飞书通知模块测试。"""

from __future__ import annotations

import queue
import threading

from axile.common.trade_channel import TradeChannel
from axile.executor import feishu_notifications as feishu_module
from axile.executor.abstract_executor import execution_lifecycle as abstract_executor_execution_lifecycle_module
from axile.executor.abstract_executor import facade as abstract_executor_facade_module
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.algorithms.core.base import AlgorithmResult
from axile.executor.feishu_notifications import send_execute_results_to_feishu
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData


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
        CTPAccountConfig.model_validate({"broker_id": "b", "investor_id": "i", "password": "p"}),
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

    def _fake_enqueue(source: object, output: object, feishu_key: object) -> None:
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
            "account_config": {"broker_id": "b", "investor_id": "i", "password": "p"},
            "curr_target": {"BTCUSDT": 0.1},
            "algorithm": {"method": "TEST"},
            "feishu_key": "hook-exec",
        }
    )

    output = executor.execute(standard_input)

    assert output.success is True
    assert len(sent) == 1
    assert sent[0][0] is executor
    assert sent[0][2] == "hook-exec"


def test_empty_positions_uses_extracted_sender(monkeypatch) -> None:
    """AbstractExecutor.empty_positions 应调用新飞书模块发送结果。"""
    executor = _FeishuAwareExecutor(TradeChannel.CTP, None)
    sent: list[tuple[object, object, object]] = []

    def _fake_sender(source: object, output: object, feishu_key: object) -> None:
        sent.append((source, output, feishu_key))

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

    monkeypatch.setattr(abstract_executor_facade_module, "send_execute_results_to_feishu", _fake_sender)
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
                    symbol="BTCUSDT",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=100.0,
                )
            ],
        ),
    )
    executor.account_config = CTPAccountConfig.model_validate({"broker_id": "b", "investor_id": "i", "password": "p"})

    result = executor.empty_positions(feishu_key="hook-empty")

    assert result.success is True
    assert len(sent) == 1
    assert sent[0][0] is executor
    assert sent[0][2] == "hook-empty"


def test_send_execute_results_to_feishu_builds_expected_card(monkeypatch) -> None:
    """飞书通知模块应构造卡片并发送到指定 webhook。"""
    pushed: list[tuple[dict[str, object], str]] = []

    def _push_card(card: dict[str, object], feishu_key: str) -> None:
        pushed.append((card, feishu_key))

    monkeypatch.setattr(feishu_module, "push_feishu_card", _push_card)

    order = UnifiedOrder(
        order_id="order-1",
        symbol="BTCUSDT",
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
                    symbol="BTCUSDT",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=100.0,
                )
            ],
        ),
        symbol_results={
            "BTCUSDT": AlgorithmResult(
                symbol="BTCUSDT",
                algorithm="TEST",
                orders=[order],
                trades=[
                    TradeRecord(
                        trade_id="trade-1",
                        symbol="BTCUSDT",
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

    send_execute_results_to_feishu(_NotificationSource(), output, "hook-demo")

    assert len(pushed) == 1
    card, key = pushed[0]
    assert key == "hook-demo"
    data = card["data"]
    assert isinstance(data, dict)
    template_variable = data["template_variable"]
    assert isinstance(template_variable, dict)
    assert template_variable["account_mark"] == "acct-demo"
    assert template_variable["algorithm"] == "Unknown"
    assert template_variable["positions"] == [
        {
            "symbol": "BTCUSDT",
            "direction": "多头",
            "market_value": "100.00",
            "volume": "1.0000",
            "target_volume": "2.0000",
            "rate": "10.00%",
        }
    ]
    assert template_variable["trades"] == [
        {
            "symbol": "BTCUSDT",
            "dt": "2026-03-25 14:00:00",
            "operate": "开多",
            "volume": "1.0000",
            "price": "101.0000",
            "order_id": "order-1",
            "trade_id": "trade-1",
        }
    ]


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
    """未提供 feishu_key 时应直接跳过，不启动 worker、不投递任务。"""
    started: list[bool] = []
    monkeypatch.setattr(
        feishu_module,
        "_ensure_feishu_notify_workers_started",
        lambda: started.append(True),
    )

    feishu_module.enqueue_execute_results_to_feishu(_NotificationSource(), _minimal_output(), None)

    assert started == []


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

    feishu_module.enqueue_execute_results_to_feishu(_NotificationSource(), _minimal_output(), "hook")

    assert len(warnings) == 1
    assert "队列已满" in warnings[0]


def test_enqueue_feishu_delivers_through_bounded_worker(monkeypatch) -> None:
    """投递的通知应由后台 worker 实际消费，参数透传正确。"""
    done = threading.Event()
    captured: list[tuple[object, object, object]] = []

    def _fake_send(source: object, output: object, feishu_key: object) -> None:
        captured.append((source, output, feishu_key))
        done.set()

    monkeypatch.setattr(feishu_module, "send_execute_results_to_feishu", _fake_send)

    source = _NotificationSource()
    feishu_module.enqueue_execute_results_to_feishu(source, _minimal_output(), "hook-worker")

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

    monkeypatch.setattr(feishu_module, "send_execute_results_to_feishu", _flaky_send)

    feishu_module.enqueue_execute_results_to_feishu(_NotificationSource(), _minimal_output(), "boom")
    feishu_module.enqueue_execute_results_to_feishu(_NotificationSource(), _minimal_output(), "ok")

    assert done.wait(timeout=5.0), "异常任务后 worker 未继续消费下一个任务"
    assert "boom" in calls and "ok" in calls

"""CTP 执行修复单元测试.

本测试文件验证 CTP 执行器的关键修复和功能改进：
1. 符号归一化（主力合约和价差合约）
2. 订单创建时的枚举值标准化
3. 清理流程的正确性
4. 现有仓位零目标添加
5. 资金验证日志包含详细信息
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, call

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.models import (
    AccountControlDecision,
    AccountControlOverride,
)
from axile.executor.account_control.presets import resolve_account_control_policy
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from axile.executor.ctp import ctp_execute as ctp_execute_module
from axile.executor.ctp.core import trader as trader_module
from axile.executor.ctp.core.objects import DirectionType, OffsetFlagType, OrderPriceType, OrderStatusType
from axile.executor.ctp.core.trader import CtpTrader
from axile.executor.ctp.ctp_execute import CTPExecutor
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import ExecutionStatus, UnifiedStandardOutput
from tests.unit.executor._account_control_test_support import normalize_account_control_override

# ============================================================================
# 测试夹具
# ============================================================================


def _module_execute(
    standard_input: UnifiedStandardInput,
    cleanup: bool = True,
) -> UnifiedStandardOutput:
    """测试侧 CTP 统一执行 helper。"""
    if not isinstance(standard_input, UnifiedStandardInput):
        raise TypeError("standard_input 必须是 UnifiedStandardInput")

    executor = ctp_execute_module.CTPExecutor(TradeChannel.CTP, standard_input.account_config)
    return executor.execute(standard_input, cleanup=cleanup)


def _module_empty_positions(
    account_config: object,
    cleanup: bool = True,
    retain_runtime: bool = False,
    **kwargs: object,
) -> UnifiedStandardOutput:
    """测试侧 CTP 清仓 helper。"""
    if not isinstance(account_config, CTPAccountConfig):
        raise TypeError("account_config 必须是 CTPAccountConfig")

    executor = ctp_execute_module.CTPExecutor(TradeChannel.CTP, account_config)
    local_kwargs = dict(kwargs)
    local_kwargs.setdefault("algorithm", {"method": "TARGET-POS-TASK", "params": {}})
    return executor.empty_positions(cleanup=cleanup, retain_runtime=retain_runtime, **local_kwargs)


class _DummyInputOrderField:
    """模拟 CThostFtdcInputOrderField 类."""

    pass


@pytest.fixture
def mock_ctp_trader():
    """创建模拟 CTP 交易器."""
    trader = CtpTrader.__new__(CtpTrader)
    trader.logger = MagicMock()
    trader.broker = "9999"
    trader.user = "000001"
    trader.order_ref = 1
    trader.api = SimpleNamespace(ReqOrderInsert=lambda _req, _request_id: 0)

    def _record_operation(operation_type: str) -> None:
        _ = operation_type

    trader._record_operation = _record_operation
    trader._unified_orders_lock = MagicMock()
    trader._unified_orders_lock.__enter__ = lambda self: self
    trader._unified_orders_lock.__exit__ = lambda self, exc_type, exc, tb: False
    trader._unified_orders = {}
    trader.front_id = 1
    trader.session_id = 2
    trader.instruments = {}
    trader.calculate_required_margin = lambda *_args, **_kwargs: 0.0
    return trader


@pytest.fixture
def mock_ctp_executor():
    """创建模拟 CTP 执行器."""
    executor = CTPExecutor.__new__(CTPExecutor)
    executor.channel_type = TradeChannel.CTP
    executor.logger = MagicMock()
    executor.trader = cast("CtpTrader", SimpleNamespace(instruments={"rb2603": object(), "m2605&m2605": object()}))
    executor.md_client = None
    executor.execution_start_time = None
    return executor


@pytest.fixture
def mock_ctp_executor_with_positions():
    """创建带现有仓位的模拟 CTP 执行器."""
    executor = CTPExecutor.__new__(CTPExecutor)
    executor.channel_type = TradeChannel.CTP
    executor.logger = MagicMock()
    executor.trader = cast(
        "CtpTrader",
        SimpleNamespace(
            instruments={"IC2603": object(), "rb2603": object()},
            get_positions_summary=lambda: [{"instrument_id": "rb2603", "net_position": 3}],
        ),
    )
    executor.md_client = None
    executor.execution_start_time = None
    return executor


@pytest.fixture
def standard_input_ctp():
    """创建标准 CTP 输入."""
    return UnifiedStandardInput.from_dict(
        {
            "channel_type": TradeChannel.CTP,
            "account_config": {
                "broker_id": "9999",
                "investor_id": "000001",
                "password": "secret",
                "td_front": "tcp://td",
                "md_front": "tcp://md",
            },
            "curr_target": {"IC2603": 1.0},
            "last_target": {},
            "trade_rules": {"IC2603": {"price": "PASSIVE"}},
            "forbidden_symbols": [],
            "risk_symbols": [],
            "algorithm": {"method": "SINGLE-MAKER", "params": {}},
        }
    )


# ============================================================================
# 辅助函数
# ============================================================================


def _build_output(channel_type: TradeChannel, standard_input: UnifiedStandardInput) -> UnifiedStandardOutput:
    """构建标准输出."""
    return UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(
            available_cash=1000.0,
            total_asset=1000.0,
            market_value=0.0,
            positions=[],
        ),
        memory={},
        inputs=standard_input,
        execution_time=0.1,
        channel_type=channel_type,
        status=ExecutionStatus.SUCCEEDED,
        success=True,
    )


def _control_clock() -> datetime:
    return datetime(2026, 3, 22, 9, 31, 15)


def _build_account_control_guard(channel: TradeChannel, override: dict[str, object]) -> AccountControlGuard:
    normalized_override = normalize_account_control_override(override)
    return AccountControlGuard(
        account_id=11,
        execution_id="exec-ctp",
        channel=channel,
        policy=resolve_account_control_policy(
            "default",
            AccountControlOverride.model_validate(normalized_override),
        ),
        baseline=AccountControlCounterSnapshot(),
        clock=_control_clock,
    )


# ============================================================================
# 测试用例
# ============================================================================


class TestCTPOrderCreation:
    """测试 CTP 订单创建."""

    def test_insert_order_creates_unified_order_with_standard_enum_values(
        self, mock_ctp_trader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试插入订单时创建统一订单并使用标准枚举值."""
        # ``insert_order`` 拆分后位于 ``trader/orders.py``，CThostFtdcInputOrderField
        # 在该子模块顶部直接 import，需要 patch 子模块。
        import importlib

        orders_module = importlib.import_module("axile.executor.ctp.core.trader.orders")
        monkeypatch.setattr(orders_module, "CThostFtdcInputOrderField", _DummyInputOrderField)

        order_ref = mock_ctp_trader.insert_order(
            instrument_id="IC2603",
            direction=DirectionType.BUY,
            offset=OffsetFlagType.OPEN,
            price_type=OrderPriceType.LIMIT_PRICE,
            limit_price=5200.0,
            volume=7,
            skip_verification=True,
        )

        created_order = mock_ctp_trader._unified_orders[order_ref]
        assert created_order.direction == "BUY"
        assert created_order.order_type == "LIMIT"

    def test_executor_set_account_control_guard_propagates_to_trader(self) -> None:
        """CTPExecutor 绑定 guard 时应同步传给 trader。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.trader = cast("CtpTrader", SimpleNamespace(set_account_control_guard=MagicMock()))
        executor.md_client = None
        executor.execution_start_time = None
        executor.set_termination_controller(None)

        guard = _build_account_control_guard(TradeChannel.CTP, {"query_order": {"per_day": 1}})
        CTPExecutor.set_account_control_guard(executor, guard)

        executor.trader.set_account_control_guard.assert_called_once_with(guard)


class TestCTPSymbolNormalization:
    """测试 CTP 符号归一化."""

    def test_execute_rejects_dict_input(self, mock_ctp_executor) -> None:
        """CTP 执行器入口只接受 UnifiedStandardInput。"""
        with pytest.raises(TypeError, match="UnifiedStandardInput"):
            CTPExecutor.execute(
                mock_ctp_executor,
                cast(
                    "UnifiedStandardInput",
                    {
                        "channel_type": TradeChannel.CTP.value,
                        "account_config": {
                            "broker_id": "9999",
                            "investor_id": "000001",
                            "password": "secret",
                            "td_front": "tcp://td",
                            "md_front": "tcp://md",
                        },
                        "curr_target": {"rb2603": 1.0},
                    },
                ),
                cleanup=False,
            )

    def test_module_execute_rejects_dict_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CTP 模块级统一执行入口也只接受 UnifiedStandardInput。"""
        monkeypatch.setattr(ctp_execute_module, "CTPExecutor", lambda *_args, **_kwargs: None)

        with pytest.raises(TypeError, match="UnifiedStandardInput"):
            _module_execute(
                cast(
                    "UnifiedStandardInput",
                    {
                        "channel_type": TradeChannel.CTP.value,
                        "account_config": {
                            "broker_id": "9999",
                            "investor_id": "000001",
                            "password": "secret",
                            "td_front": "tcp://td",
                            "md_front": "tcp://md",
                        },
                        "curr_target": {"rb2603": 1.0},
                    },
                )
            )

    def test_module_empty_positions_rejects_dict_account_config(self) -> None:
        """CTP 模块级清仓入口只接受 CTPAccountConfig。"""
        with pytest.raises(TypeError, match="CTPAccountConfig"):
            _module_empty_positions(
                cast(
                    "CTPAccountConfig",
                    {
                        "broker_id": "9999",
                        "investor_id": "000001",
                        "password": "secret",
                        "td_front": "tcp://td",
                        "md_front": "tcp://md",
                    },
                )
            )

    def test_normalizes_main_contract_and_spread_symbols(
        self, mock_ctp_executor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试主力合约和价差合约符号归一化."""
        captured: dict[str, UnifiedStandardInput] = {}

        def _fake_base_execute(
            self: AbstractExecutor,
            standard_input: UnifiedStandardInput,
            cleanup: bool = True,
            retain_runtime: bool = False,  # noqa: FBT001, FBT002
        ) -> UnifiedStandardOutput:
            _ = (cleanup, retain_runtime)
            captured["standard_input"] = standard_input
            return _build_output(self.channel_type, standard_input)

        def _fake_format_symbol(symbol: str) -> str:
            if symbol == "SQrb9001":
                return "rb2603"
            return symbol

        monkeypatch.setattr(AbstractExecutor, "execute", _fake_base_execute)
        monkeypatch.setattr(ctp_execute_module, "format_symbol", _fake_format_symbol, raising=False)

        standard_input = UnifiedStandardInput.from_dict(
            {
                "channel_type": TradeChannel.CTP,
                "account_config": {
                    "broker_id": "9999",
                    "investor_id": "000001",
                    "password": "secret",
                    "td_front": "tcp://td",
                    "md_front": "tcp://md",
                },
                "curr_target": {"SQrb9001": 0.5, "SP m2605&m2605": 0.2},
                "last_target": {"SQrb9001": 0.0, "SP m2605&m2605": 0.1},
                "trade_rules": {
                    "SQrb9001": {"price": "PASSIVE"},
                    "SP m2605&m2605": {"price": "ACTIVE"},
                },
                "forbidden_symbols": ["SP m2605&m2605"],
                "risk_symbols": ["SQrb9001"],
                "algorithm": {"method": "SINGLE-MAKER", "params": {}},
            }
        )

        original_curr_target = dict(standard_input.curr_target)
        original_last_target = dict(standard_input.last_target)
        original_trade_rules = {symbol: dict(rule) for symbol, rule in standard_input.trade_rules.items()}
        original_forbidden_symbols = list(standard_input.forbidden_symbols)
        original_risk_symbols = list(standard_input.risk_symbols)

        CTPExecutor.execute(mock_ctp_executor, standard_input, cleanup=False)

        normalized = captured["standard_input"]
        assert normalized.curr_target == {"rb2603": 0.5, "m2605&m2605": 0.2}
        assert normalized.last_target == {"rb2603": 0.0, "m2605&m2605": 0.1}
        assert normalized.trade_rules == {
            "rb2603": {"price": "PASSIVE"},
            "m2605&m2605": {"price": "ACTIVE"},
        }
        assert normalized.forbidden_symbols == ["m2605&m2605"]
        assert normalized.risk_symbols == ["rb2603"]
        assert standard_input.curr_target == original_curr_target
        assert standard_input.last_target == original_last_target
        assert standard_input.trade_rules == original_trade_rules
        assert standard_input.forbidden_symbols == original_forbidden_symbols
        assert standard_input.risk_symbols == original_risk_symbols


class TestCTPCleanup:
    """测试 CTP 清理流程."""

    def test_cleanup_closes_market_data_and_trader_clients(self) -> None:
        """测试清理时关闭行情客户端和交易器."""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.md_client = MagicMock()
        executor.trader = MagicMock()

        CTPExecutor._cleanup(executor)

        executor.md_client.close.assert_called_once_with()
        executor.trader.close.assert_called_once_with()

    def test_cleanup_requests_stop_before_closing_clients(self) -> None:
        """测试清理前会先请求停止，避免查询等待继续阻塞。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.md_client = MagicMock()
        executor.trader = MagicMock()

        CTPExecutor._cleanup(executor)

        executor.md_client.assert_has_calls([call.request_stop(), call.close()])
        executor.trader.assert_has_calls([call.request_stop(), call.close()])

    def test_get_pending_orders_delegates_to_local_snapshot_filter(self) -> None:
        """测试挂单查询会委托给 trader 本地订单快照并按 symbol 过滤."""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        pending_order = MagicMock(symbol="rb2603", extra={"status": OrderStatusType.NO_TRADE_QUEUEING})
        executor.trader = MagicMock(get_unified_orders=MagicMock(return_value=[pending_order]))
        executor.md_client = MagicMock()

        result = CTPExecutor.get_pending_orders(executor, "rb2603")

        assert result == [pending_order]
        executor.trader.get_unified_orders.assert_called_once_with()

    def test_get_pending_orders_with_none_returns_all_pending_orders(self) -> None:
        """测试 symbol=None 时返回全部未完成订单。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        pending_order_1 = MagicMock(symbol="rb2603", extra={"status": OrderStatusType.NO_TRADE_QUEUEING})
        pending_order_2 = MagicMock(symbol="ag2606", extra={"status": OrderStatusType.NOT_TOUCHED})
        executor.trader = MagicMock(get_unified_orders=MagicMock(return_value=[pending_order_1, pending_order_2]))
        executor.md_client = MagicMock()

        result = CTPExecutor.get_pending_orders(executor, None)

        assert result == [pending_order_1, pending_order_2]
        executor.trader.get_unified_orders.assert_called_once_with()

    def test_query_trades_delegates_to_trader_and_filters_by_order(self) -> None:
        """测试成交查询会委托给 trader 并按 symbol / order_id 过滤。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        matching_trade = MagicMock(InstrumentID="rb2603", OrderSysID="123", OrderRef="321")
        matching_trade.to_unified_trade.return_value = SimpleNamespace(trade_id="trade-1")
        ignored_trade = MagicMock(InstrumentID="ag2606", OrderSysID="456", OrderRef="654")
        ignored_trade.to_unified_trade.return_value = SimpleNamespace(trade_id="trade-2")
        executor.trader = MagicMock(
            _query_trades_impl=MagicMock(return_value={"1": matching_trade, "2": ignored_trade})
        )
        executor.md_client = MagicMock()

        result = CTPExecutor.query_trades(executor, "rb2603", "123")

        assert result == [matching_trade.to_unified_trade.return_value]
        executor.trader._query_trades_impl.assert_called_once_with("rb2603")


class TestCTPAccountControl:
    """测试 CTP 账户控制语义。"""

    def test_get_pending_orders_uses_query_budget_before_local_snapshot_access(self) -> None:
        """当前实现即便读取本地快照，也要按远端实时 query_order 语义计数。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.trader = MagicMock(get_unified_orders=MagicMock(return_value=[]))
        executor.md_client = None
        executor.execution_start_time = None
        guard = _build_account_control_guard(
            TradeChannel.CTP,
            {"query_order": {"per_day": 0}},
        )
        executor.set_account_control_guard(guard)

        with pytest.raises(AccountControlBlockedError):
            CTPExecutor.get_pending_orders(executor, "rb2603")

        executor.trader.get_unified_orders.assert_not_called()
        _, events = guard.flush_records()
        assert len(events) == 1
        assert events[0].operation == "query_order"
        assert events[0].decision == AccountControlDecision.BLOCKED

    def test_get_pending_orders_consumes_query_budget(self) -> None:
        """按 symbol 查询挂单应记为 query_order。"""
        pending_order = UnifiedOrder.create(
            order_id="ctp-1",
            symbol="rb2603",
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=1,
            price=3500,
            status="待成交",
            create_time="2026-03-22T09:31:00",
            channel_type=TradeChannel.CTP,
        )
        pending_order.extra["status"] = OrderStatusType.NO_TRADE_QUEUEING
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.trader = MagicMock(get_unified_orders=MagicMock(return_value=[pending_order]))
        executor.md_client = None
        executor.execution_start_time = None
        guard = _build_account_control_guard(
            TradeChannel.CTP,
            {"query_order": {"per_day": 1}},
        )
        executor.set_account_control_guard(guard)

        result = CTPExecutor.get_pending_orders(executor, "rb2603")

        assert result == [pending_order]
        executor.trader.get_unified_orders.assert_called_once_with()
        _, events = guard.flush_records()
        assert len(events) == 1
        assert events[0].operation == "query_order"
        assert events[0].decision == AccountControlDecision.ALLOWED
        assert events[0].outcome != "pending"

    def test_query_trades_uses_query_budget_before_trader_access(self) -> None:
        """命中 query_trades 限制时不应继续访问 trader。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.trader = MagicMock(_query_trades_impl=MagicMock(return_value={}))
        executor.md_client = None
        executor.execution_start_time = None
        guard = _build_account_control_guard(
            TradeChannel.CTP,
            {
                "query_trades": {
                    "per_day": {"limit": 0, "on_trigger": "block"},
                }
            },
        )
        executor.set_account_control_guard(guard)

        with pytest.raises(AccountControlBlockedError):
            CTPExecutor.query_trades(executor, "rb2603", "123")

        executor.trader._query_trades_impl.assert_not_called()
        _, events = guard.flush_records()
        assert len(events) == 1
        assert events[0].operation == "query_trades"
        assert events[0].decision == AccountControlDecision.BLOCKED

    def test_execution_internal_query_trades_share_single_remote_snapshot(self) -> None:
        """execution-internal 成交查询应共享一次 trader 原生远端抓取。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        matching_trade = MagicMock(InstrumentID="rb2603", OrderSysID="123", OrderRef="321")
        matching_trade.to_unified_trade.return_value = SimpleNamespace(trade_id="trade-1", extra={})
        other_trade = MagicMock(InstrumentID="ag2606", OrderSysID="456", OrderRef="654")
        other_trade.to_unified_trade.return_value = SimpleNamespace(trade_id="trade-2", extra={})
        executor.trader = SimpleNamespace(
            _query_trades_impl=MagicMock(return_value={"1": matching_trade, "2": other_trade}),
            set_account_control_guard=lambda _guard: None,
        )
        executor.md_client = None
        executor.execution_start_time = None
        guard = _build_account_control_guard(
            TradeChannel.CTP,
            {"query_trades": {"per_day": 1}},
        )
        executor.set_account_control_guard(guard)

        rb_trades = executor._query_trades_for_execution("rb2603", "123")
        ag_trades = executor._query_trades_for_execution("ag2606", "456")

        assert rb_trades == [matching_trade.to_unified_trade.return_value]
        assert ag_trades == [other_trade.to_unified_trade.return_value]
        executor.trader._query_trades_impl.assert_called_once_with("")

        _, events = guard.flush_records()
        assert len(events) == 1
        assert events[0].operation == "query_trades"
        assert events[0].decision == AccountControlDecision.ALLOWED
        assert events[0].symbol is None
        assert events[0].metadata["query_scope"] == "snapshot"

    def test_callback_dispatch_invalidates_execution_query_runtime(self) -> None:
        """CTP 订单和成交回调到达时应 patch execution 共享查询快照。"""
        executor = CTPExecutor.__new__(CTPExecutor)
        executor.channel_type = TradeChannel.CTP
        executor.logger = MagicMock()
        executor.trader = SimpleNamespace(
            _callback_manager=trader_module.CallbackManager(logger=executor.logger),
        )
        patched_orders: list[UnifiedOrder] = []
        patched_trades: list[TradeRecord] = []

        class _Runtime:
            def apply_pending_order_update(self, order: UnifiedOrder) -> None:
                patched_orders.append(order)

            def apply_trade_record(self, trade: TradeRecord) -> None:
                patched_trades.append(trade)

        executor.set_active_execution_query_runtime(_Runtime())
        CTPExecutor._register_execution_query_runtime_callback_observers(executor)

        order = UnifiedOrder.create(
            order_id="ctp-1",
            symbol="rb2603",
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=1,
            price=3500,
            status="待成交",
            channel_type=TradeChannel.CTP,
        )
        trade = TradeRecord.create(
            trade_id="trade-1",
            trade_time="2026-03-22T09:31:15",
            trade_volume=1,
            trade_price=3500,
            extra={"symbol": "rb2603", "order_id": "123"},
        )
        executor.trader._callback_manager.dispatch_order_callback(order)
        executor.trader._callback_manager.dispatch_trade_callback(trade)

        assert patched_orders == [order]
        assert patched_trades == [trade]


class TestCTPZeroTargets:
    """测试 CTP 零目标添加."""

    def test_adds_zero_targets_for_existing_account_positions(
        self,
        mock_ctp_executor_with_positions,
        standard_input_ctp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """测试为现有账户仓位添加零目标."""
        captured: dict[str, UnifiedStandardInput] = {}

        def _fake_base_execute(
            self: AbstractExecutor,
            standard_input: UnifiedStandardInput,
            cleanup: bool = True,
            retain_runtime: bool = False,  # noqa: FBT001, FBT002
        ) -> UnifiedStandardOutput:
            _ = (cleanup, retain_runtime)
            captured["standard_input"] = standard_input
            return _build_output(self.channel_type, standard_input)

        monkeypatch.setattr(AbstractExecutor, "execute", _fake_base_execute)

        CTPExecutor.execute(mock_ctp_executor_with_positions, standard_input_ctp, cleanup=False)

        normalized = captured["standard_input"]
        assert normalized.curr_target == {"IC2603": 1.0, "rb2603": 0.0}


class TestCTPFundVerification:
    """测试 CTP 资金验证."""

    def test_verify_open_position_fund_success_log_includes_symbol_volume_and_margin(self, mock_ctp_trader) -> None:
        """测试资金验证成功日志包含合约代码、开仓手数和保证金信息."""
        mock_ctp_trader.account = SimpleNamespace(Available=2_636_537.23)
        mock_ctp_trader.calculate_required_margin = lambda *_args, **_kwargs: 85_728.0

        ok, message = mock_ctp_trader._verify_open_position_fund("IC2603", DirectionType.BUY, 5200.0, 7)

        assert ok is True
        assert message == "资金验证通过"
        mock_ctp_trader.logger.info.assert_called_once_with(
            "✅ 资金验证通过：IC2603 开仓 7手需保证金 85,728.00元，可用资金 2,636,537.23元"
        )

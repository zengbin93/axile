"""
订单操作辅助函数单元测试.

测试 order_helper 模块中的所有公共函数。
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from axile.executor.algorithms.exceptions import SubMinQuantityError
from axile.executor.algorithms.utils.order_helper import (
    determine_position_side,
    resolve_reduce_intent,
    setup_order_tracker,
    submit_and_track_order,
    teardown_order_tracker,
)
from axile.executor.models.unified_account_assets import PositionDirection
from axile.executor.models.unified_order import OrderDirection, OrderType
from axile.executor.models.unified_price import UnifiedPriceData


class TestDeterminePositionSide:
    """测试 determine_position_side 函数."""

    @pytest.fixture
    def executor(self):
        """创建模拟的执行器."""
        executor = MagicMock()
        executor.logger = MagicMock()
        executor.symbol = "rb2610"
        return executor

    @pytest.fixture
    def account_assets_with_long(self):
        """创建带有多头持仓的账户资产."""
        assets = MagicMock()
        return assets

    @pytest.fixture
    def account_assets_with_short(self):
        """创建带有空头持仓的账户资产."""
        assets = MagicMock()
        return assets

    @pytest.fixture
    def account_assets_empty(self):
        """创建空持仓的账户资产."""
        assets = MagicMock()
        return assets

    def test_sell_closing_long_position(self, executor, account_assets_with_long):
        """测试卖出时平多头持仓."""
        executor.symbol = "rb2610"
        executor.get_positions = Mock(return_value=[(1.0, PositionDirection.LONG), (0.5, PositionDirection.SHORT)])

        result = determine_position_side(
            executor,
            OrderDirection.SELL,
            account_assets_with_long,
        )

        assert result == {"position_side": "LONG"}
        assert executor.logger.debug.called

    def test_buy_closing_short_position(self, executor, account_assets_with_short):
        """测试买入时平空头持仓."""
        executor.symbol = "ag2612"
        executor.get_positions = Mock(return_value=[(0.5, PositionDirection.SHORT), (1.0, PositionDirection.LONG)])

        result = determine_position_side(
            executor,
            OrderDirection.BUY,
            account_assets_with_short,
        )

        assert result == {"position_side": "SHORT"}
        assert executor.logger.debug.called

    def test_sell_no_long_position(self, executor, account_assets_empty):
        """测试卖出但没有多头持仓."""
        executor.symbol = "rb2610"
        executor.get_positions = Mock(return_value=[])

        result = determine_position_side(
            executor,
            OrderDirection.SELL,
            account_assets_empty,
        )

        assert result == {}
        assert not executor.logger.debug.called

    def test_buy_no_short_position(self, executor, account_assets_empty):
        """测试买入但没有空头持仓."""
        executor.symbol = "ag2612"
        executor.get_positions = Mock(return_value=[])

        result = determine_position_side(
            executor,
            OrderDirection.BUY,
            account_assets_empty,
        )

        assert result == {}
        assert not executor.logger.debug.called

    def test_get_positions_error_handling(self, executor):
        """测试获取持仓失败时的错误处理."""
        assets = MagicMock()
        executor.symbol = "rb2610"
        executor.get_positions = Mock(side_effect=Exception("Connection error"))

        result = determine_position_side(
            executor,
            OrderDirection.SELL,
            assets,
        )

        # 应该返回空字典并记录警告
        assert result == {}
        # 验证 warning 被调用
        executor.logger.warning.assert_called_once()
        # 验证调用包含错误信息
        call_args = str(executor.logger.warning.call_args)
        assert "获取 rb2610 持仓失败" in call_args


class TestSetupOrderTracker:
    """测试 setup_order_tracker 函数."""

    @pytest.fixture
    def executor(self):
        """创建模拟的执行器."""
        executor = MagicMock()
        executor.logger = MagicMock()
        executor.symbol = "rb2610"
        return executor

    @pytest.fixture
    def price_data(self):
        """创建模拟的单品种市场数据."""
        return UnifiedPriceData(
            symbol="rb2610",
            last_price=50000,
            bid_price=49990,
            ask_price=50010,
            bid_volume=1.0,
            ask_volume=1.0,
            volume=10.0,
            turnover=1000.0,
            timestamp=1,
            update_time="2026-03-22T00:00:00",
        )

    @pytest.fixture
    def chase_config(self):
        """创建追单配置."""
        return Mock(enabled=True)

    @pytest.fixture
    def tracker(self):
        """创建模拟的订单跟踪器."""
        tracker = MagicMock()
        tracker.latest_prices = {}
        return tracker

    def test_setup_with_chase_enabled(self, executor, price_data, chase_config, tracker):
        """测试启用追单时的设置."""
        with patch(
            "axile.executor.algorithms.utils.order_helper.OrderTracker",
            return_value=tracker,
        ):
            result = setup_order_tracker(
                executor,
                price_data,
                chase_config,
            )

            assert result is tracker

            # WebSocket 预热由执行编排层负责
            executor.initialize_websocket.assert_not_called()

            # 验证订单回调注册
            assert executor.register_order_callback.called

            # 验证成交回调注册
            executor.register_trade_callback.assert_called_once_with(tracker.on_trade_record)

            # 验证价格回调注册
            assert executor.register_price_callback.called

            # 验证价格数据初始化
            assert tracker.latest_prices == {"rb2610": price_data}

            # 验证日志记录
            assert executor.logger.debug.called

    def test_setup_without_chase(self, executor, price_data, tracker):
        """测试未启用追单时的设置."""
        with patch(
            "axile.executor.algorithms.utils.order_helper.OrderTracker",
            return_value=tracker,
        ):
            result = setup_order_tracker(
                executor,
                price_data,
                None,  # 无追单配置
            )

            assert result is tracker

            # WebSocket 预热由执行编排层负责
            executor.initialize_websocket.assert_not_called()

            # 验证订单回调注册
            assert executor.register_order_callback.called

            # 验证成交回调注册
            executor.register_trade_callback.assert_called_once_with(tracker.on_trade_record)

            # 验证价格回调未注册
            assert not executor.register_price_callback.called

    def test_setup_with_chase_enabled_registers_price_callback_without_initial_tick(
        self,
        executor,
        chase_config,
        tracker,
    ):
        """启用追单时，即使没有首个快照也应注册价格回调。"""
        with patch(
            "axile.executor.algorithms.utils.order_helper.OrderTracker",
            return_value=tracker,
        ):
            result = setup_order_tracker(
                executor,
                None,
                chase_config,
            )

            assert result is tracker
            executor.register_trade_callback.assert_called_once_with(tracker.on_trade_record)
            executor.register_price_callback.assert_called_once_with(tracker.on_price_update)
            assert tracker.latest_prices == {}


class TestTeardownOrderTracker:
    """测试 teardown_order_tracker 函数."""

    @pytest.fixture
    def executor(self):
        """创建模拟的执行器."""
        executor = MagicMock()
        executor.logger = MagicMock()
        executor.symbol = "rb2610"
        return executor

    @pytest.fixture
    def tracker(self):
        """创建模拟的订单跟踪器."""
        return MagicMock()

    @pytest.fixture
    def chase_config(self):
        """创建追单配置."""
        return Mock(enabled=True)

    def test_teardown_with_chase(self, executor, tracker, chase_config):
        """测试启用追单时的清理."""
        teardown_order_tracker(executor, tracker, chase_config)

        # 验证订单回调注销
        assert executor.unregister_order_callback.called

        # 验证成交回调注销
        executor.unregister_trade_callback.assert_called_once_with(tracker.on_trade_record)

        # 验证价格回调注销
        assert executor.unregister_price_callback.called

        # 验证日志记录
        assert executor.logger.debug.called

    def test_teardown_without_chase(self, executor, tracker):
        """测试未启用追单时的清理."""
        teardown_order_tracker(executor, tracker, None)

        # 验证订单回调注销
        assert executor.unregister_order_callback.called

        # 验证成交回调注销
        executor.unregister_trade_callback.assert_called_once_with(tracker.on_trade_record)

        # 验证价格回调未注销
        assert not executor.unregister_price_callback.called

    def test_teardown_unregister_order_callback_error(self, executor, tracker):
        """测试注销订单回调失败的情况."""
        # 模拟注销失败
        executor.unregister_order_callback = Mock(side_effect=Exception("Unregister error"))

        # 应该不抛出异常，只记录警告
        teardown_order_tracker(executor, tracker, None)

        assert executor.logger.warning.called

    def test_teardown_unregister_price_callback_error(self, executor, tracker):
        """测试注销价格回调失败的情况."""
        chase_config = Mock(enabled=True)

        # 模拟注销订单回调成功，但注销价格回调失败
        executor.unregister_order_callback = Mock(return_value=None)
        executor.unregister_price_callback = Mock(side_effect=Exception("Unregister error"))

        # 应该不抛出异常，只记录警告
        teardown_order_tracker(executor, tracker, chase_config)

        assert executor.logger.warning.called


class TestSubmitAndTrackOrder:
    """测试 submit_and_track_order 函数."""

    @pytest.fixture
    def executor(self):
        """创建模拟的执行器."""
        executor = MagicMock()
        executor.logger = MagicMock()
        executor.symbol = "rb2610"
        return executor

    @pytest.fixture
    def tracker(self):
        """创建模拟的订单跟踪器."""
        tracker = MagicMock()
        tracker.latest_prices = {}
        return tracker

    @pytest.fixture
    def order(self):
        """创建模拟的订单对象."""
        order = MagicMock()
        order.order_id = "test_order_123"
        order.price = 50000.0
        order.volume = 1.0
        return order

    def test_submit_order_success(self, executor, tracker, order):
        """测试成功提交订单."""
        # 模拟 place_order 返回订单
        executor.place_order = Mock(return_value=order)

        result = submit_and_track_order(
            executor,
            tracker,
            OrderDirection.BUY,
            OrderType.LIMIT,
            1.0,
            50000.0,
            target_volume=2.0,
            current_volume=1.0,
            position_side="LONG",
        )

        # 验证下单被调用
        executor.place_order.assert_called_once_with(
            OrderDirection.BUY,
            OrderType.LIMIT,
            1.0,
            50000.0,
            position_side="LONG",
        )

        # 验证订单被添加到跟踪器
        assert tracker.add_order.called

        # 验证日志记录
        assert executor.logger.debug.called

        # 验证返回值
        assert result.order_id == "test_order_123"

    def test_submit_order_with_extra_kwargs(self, executor, tracker, order):
        """测试带额外参数的订单提交."""
        executor.place_order = Mock(return_value=order)

        result = submit_and_track_order(
            executor,
            tracker,
            OrderDirection.SELL,
            OrderType.MARKET,
            0.5,
            0.0,
            target_volume=0.0,
            current_volume=0.5,
            position_side="SHORT",
            time_in_force="GTC",  # 额外参数
        )

        # 验证额外参数被传递
        executor.place_order.assert_called_once_with(
            OrderDirection.SELL,
            OrderType.MARKET,
            0.5,
            0.0,
            position_side="SHORT",
            time_in_force="GTC",
        )
        call_kwargs = executor.place_order.call_args[1]
        assert result is order
        assert call_kwargs["position_side"] == "SHORT"
        assert call_kwargs["time_in_force"] == "GTC"

    def test_submit_order_without_position_side(self, executor, tracker, order):
        """测试不带 position_side 的订单提交."""
        executor.place_order = Mock(return_value=order)

        result = submit_and_track_order(
            executor,
            tracker,
            OrderDirection.BUY,
            OrderType.LIMIT,
            1.0,
            50000.0,
            target_volume=2.0,
            current_volume=1.0,
            # 不提供 position_side
        )

        # 验证下单被调用
        assert executor.place_order.called

        # 验证 add_order 被调用，且 position_side 为 None
        tracker.add_order.assert_called()
        call_args = tracker.add_order.call_args
        assert result is order
        assert call_args[1]["position_side"] is None


class TestIntegration:
    """集成测试：测试工具函数的组合使用."""

    @pytest.fixture
    def mock_executor(self):
        """创建完整的模拟执行器."""
        executor = MagicMock()
        executor.logger = MagicMock()
        executor.symbol = "rb2610"
        return executor

    def test_full_order_workflow(self, mock_executor):
        """测试完整的订单工作流程."""
        # 模拟订单
        order = MagicMock()
        order.order_id = "test_order_123"
        mock_executor.place_order = Mock(return_value=order)

        with patch("axile.executor.algorithms.utils.order_helper.OrderTracker") as mock_tracker_class:
            mock_tracker = MagicMock()
            mock_tracker_class.return_value = mock_tracker
            mock_tracker.latest_prices = {}

            # 步骤 1: 设置跟踪器
            tracker = setup_order_tracker(
                mock_executor,
                UnifiedPriceData(
                    symbol="rb2610",
                    last_price=50000,
                    bid_price=49990,
                    ask_price=50010,
                    bid_volume=1.0,
                    ask_volume=1.0,
                    volume=10.0,
                    turnover=1000.0,
                    timestamp=1,
                    update_time="2026-03-22T00:00:00",
                ),
                None,  # 不启用追单
            )

            # 步骤 2: 提交订单
            result = submit_and_track_order(
                mock_executor,
                tracker,
                OrderDirection.BUY,
                OrderType.LIMIT,
                1.0,
                50000.0,
                target_volume=2.0,
                current_volume=1.0,
            )

            # 步骤 3: 清理跟踪器
            teardown_order_tracker(mock_executor, tracker, None)

            # 验证完整流程
            mock_executor.initialize_websocket.assert_not_called()
            assert mock_executor.register_order_callback.called
            assert mock_executor.unregister_order_callback.called
            assert mock_executor.place_order.called
            assert result.order_id == "test_order_123"


def _intent_executor(min_notional, last_price=0.0):
    """构造供 resolve_reduce_intent 测试使用的执行器桩."""
    executor = MagicMock()
    executor.symbol = "rb2610"
    executor.logger = MagicMock()
    executor.get_min_notional = Mock(return_value=min_notional)
    if last_price:
        market = MagicMock()
        market.last_price = last_price
        market.bid_price = last_price
        market.ask_price = last_price
        executor.get_market_data = Mock(return_value=market)
    return executor


class TestResolveReduceIntent:
    """测试 resolve_reduce_intent 单向持仓决策表."""

    @pytest.mark.parametrize(
        ("min_notional", "direction", "volume", "target_volume", "current_volume", "price", "action", "reduce_only"),
        [
            # 退化：渠道无最小名义价值信息 / 非正 → 维持既有行为
            (None, OrderDirection.BUY, 0.3, 1.0, 0.0, 100.0, "SEND", False),
            (0.0, OrderDirection.BUY, 0.3, 1.0, 0.0, 100.0, "SEND", False),
            # 名义达标 → 照常发，不置 reduce_only
            (50.0, OrderDirection.BUY, 1.0, 2.0, 1.0, 100.0, "SEND", False),
            # 纯减仓且名义不足 → 借 reduceOnly 突破
            (50.0, OrderDirection.SELL, 0.3, 0.7, 1.0, 100.0, "SEND", True),
            (50.0, OrderDirection.BUY, 0.3, -0.7, -1.0, 100.0, "SEND", True),
            # 清仓 dust（目标为 0）→ 落入纯减仓分支
            (50.0, OrderDirection.SELL, 0.3, 0.0, 0.3, 100.0, "SEND", True),
            # 加仓 / 从零开仓且名义不足 → 被逼的死区，跳过
            (50.0, OrderDirection.BUY, 0.3, 1.3, 1.0, 100.0, "SKIP", False),
            (50.0, OrderDirection.BUY, 0.3, 0.3, 0.0, 100.0, "SKIP", False),
            # 穿零翻向且名义不足 → 含反向开仓段，不可 reduceOnly，跳过
            (50.0, OrderDirection.SELL, 0.4, -0.2, 0.2, 100.0, "SKIP", False),
            # 穿零翻向但名义达标 → 照常发，且绝不置 reduce_only（否则封顶欠成交）
            (50.0, OrderDirection.SELL, 2.0, -1.0, 1.0, 100.0, "SEND", False),
        ],
    )
    def test_decision_table(
        self, min_notional, direction, volume, target_volume, current_volume, price, action, reduce_only
    ):
        """逐条覆盖单向决策表的每个分支."""
        executor = _intent_executor(min_notional)
        decision = resolve_reduce_intent(executor, direction, volume, target_volume, current_volume, price)
        assert decision.action == action
        assert decision.reduce_only is reduce_only

    def test_market_order_uses_reference_price_from_snapshot(self):
        """市价单价格为 0 时应回退到行情快照估算名义价值."""
        executor = _intent_executor(50.0, last_price=100.0)
        decision = resolve_reduce_intent(executor, OrderDirection.SELL, 0.3, 0.0, 1.0, 0.0)
        assert decision.action == "SEND"
        assert decision.reduce_only is True

    def test_market_order_falls_back_to_bid_ask_mid(self):
        """最新价缺失时应退到买一卖一中值估算名义价值."""
        executor = _intent_executor(50.0)
        market = MagicMock()
        market.last_price = 0.0
        market.bid_price = 99.0
        market.ask_price = 101.0
        executor.get_market_data = Mock(return_value=market)
        # 中值 100，纯减仓 0.3 * 100 = 30 < 50 → 借 reduceOnly 突破。
        decision = resolve_reduce_intent(executor, OrderDirection.SELL, 0.3, 0.0, 1.0, 0.0)
        assert decision.action == "SEND"
        assert decision.reduce_only is True

    def test_sends_when_reference_price_unavailable(self):
        """无法估算名义价值时不阻断，退化为照常下单."""
        executor = _intent_executor(50.0)
        executor.get_market_data = Mock(return_value=None)
        decision = resolve_reduce_intent(executor, OrderDirection.SELL, 0.3, 0.0, 1.0, 0.0)
        assert decision.action == "SEND"
        assert decision.reduce_only is False


class TestSubmitAndTrackOrderProjection:
    """测试 submit_and_track_order 接入投影后的跳过与 reduce_only 注入."""

    def _executor(self, min_notional=50.0, last_price=100.0):
        executor = MagicMock()
        executor.symbol = "rb2610"
        executor.logger = MagicMock()
        executor.get_min_notional = Mock(return_value=min_notional)
        market = MagicMock()
        market.last_price = last_price
        market.bid_price = last_price
        market.ask_price = last_price
        executor.get_market_data = Mock(return_value=market)
        return executor

    def test_skip_sub_min_increase_returns_none_and_audits(self):
        """加仓 sub-min 应跳过：返回 None、不下单、不入 tracker、记审计事件."""
        executor = self._executor()
        tracker = MagicMock()

        result = submit_and_track_order(
            executor,
            tracker,
            OrderDirection.BUY,
            OrderType.MARKET,
            0.3,
            0.0,
            target_volume=0.3,
            current_volume=0.0,
        )

        assert result is None
        executor.place_order.assert_not_called()
        tracker.add_order.assert_not_called()
        executor.emit_audit_event.assert_called_once()
        assert executor.emit_audit_event.call_args.kwargs["reason_code"] == "COMMON.SUB_MIN_NOTIONAL"

    def test_sub_min_qty_from_channel_skips_and_audits(self):
        """渠道取整后归零抛 SubMinQuantityError 应跳过：返回 None、不入 tracker、记 SUB_MIN_QTY 事件."""
        executor = self._executor()
        executor.place_order = Mock(side_effect=SubMinQuantityError("qty rounded to 0"))
        tracker = MagicMock()

        # volume*ref=1.0*100 >= min_notional=50 → resolve_reduce_intent 判 SEND，进入 place_order。
        result = submit_and_track_order(
            executor,
            tracker,
            OrderDirection.SELL,
            OrderType.MARKET,
            1.0,
            0.0,
            target_volume=0.0,
            current_volume=1.0,
        )

        assert result is None
        executor.place_order.assert_called_once()
        tracker.add_order.assert_not_called()
        assert executor.emit_audit_event.call_args.kwargs["reason_code"] == "COMMON.SUB_MIN_QTY"

    def test_pure_reduce_injects_reduce_only(self):
        """纯减仓 sub-min 应注入 reduce_only 后照常下单."""
        executor = self._executor()
        order = MagicMock()
        order.order_id = "oid"
        executor.place_order = Mock(return_value=order)
        tracker = MagicMock()

        result = submit_and_track_order(
            executor,
            tracker,
            OrderDirection.SELL,
            OrderType.MARKET,
            0.3,
            0.0,
            target_volume=0.7,
            current_volume=1.0,
        )

        assert result is order
        assert executor.place_order.call_args.kwargs["reduce_only"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

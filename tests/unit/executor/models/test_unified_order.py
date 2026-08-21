"""
测试 axile.executor.unified_order 模块.

测试统一订单数据模型的功能，包括订单创建、成交记录管理和渠道特定功能。
"""

from typing import cast

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_order import (
    OrderDirection,
    OrderType,
    TradeRecord,
    UnifiedOrder,
)


class TestTradeRecord:
    """测试成交记录."""

    def test_create_trade_record(self) -> None:
        """测试创建成交记录."""
        trade = TradeRecord.create(
            trade_id="T001",
            symbol="BTCUSDT",
            order_id="ORDER-1",
            trade_volume=0.1,
            trade_price=30000.0,
        )

        assert trade.trade_id == "T001"
        assert trade.symbol == "BTCUSDT"
        assert trade.order_id == "ORDER-1"
        assert trade.trade_volume == 0.1
        assert trade.trade_price == 30000.0
        assert trade.trade_value == 3000.0  # 0.1 * 30000.0
        assert trade.trade_time is not None

    def test_trade_record_with_custom_time(self) -> None:
        """测试带自定义时间的成交记录."""
        custom_time = "2023-12-21T10:30:00.000Z"
        trade = TradeRecord.create(
            trade_id="T002",
            trade_time=custom_time,
            trade_volume=0.5,
            trade_price=40000.0,
        )

        assert trade.trade_time == custom_time
        assert trade.trade_value == 20000.0  # 0.5 * 40000.0

    def test_trade_record_str_method(self) -> None:
        """测试成交记录的字符串表示."""
        trade = TradeRecord.create(
            trade_id="T003",
            trade_volume=1.0,
            trade_price=50000.0,
        )

        str_repr = str(trade)
        assert "TradeRecord" in str_repr
        assert "id=T003" in str_repr
        assert "volume=1.0" in str_repr
        assert "price=50000.0" in str_repr

    def test_trade_record_extra_field(self) -> None:
        """测试成交记录的额外字段."""
        extra_data: dict[str, object] = {"source": "exchange", "fee": 0.001}
        trade = TradeRecord(
            trade_id="T004",
            symbol="BTCUSDT",
            order_id="ORDER-4",
            trade_time="2023-12-21T10:30:00.000Z",
            trade_volume=2.0,
            trade_price=25000.0,
            trade_value=50000.0,
            extra=extra_data,
        )

        assert trade.extra == extra_data
        assert trade.extra["source"] == "exchange"
        assert trade.extra["fee"] == 0.001


class TestUnifiedOrderCreation:
    """测试统一订单创建."""

    def test_create_basic_order(self) -> None:
        """测试创建基础订单."""
        order = UnifiedOrder.create(
            order_id="ORDER001",
            symbol="BTC/USDT",
            direction="BUY",
            order_type="LIMIT",
            volume=0.1,
            price=30000.0,
        )

        assert order.order_id == "ORDER001"
        assert order.symbol == "BTC/USDT"
        assert order.direction == OrderDirection.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.volume == 0.1
        assert order.price == 30000.0
        assert order.status == OrderStatus.SUBMITTED
        assert order.filled_volume == 0.0
        assert order.avg_price == 0.0

    def test_create_order_with_custom_status(self) -> None:
        """测试创建带自定义状态的订单."""
        order = UnifiedOrder.create(
            order_id="ORDER002",
            symbol="ETH/USDT",
            direction="SELL",
            order_type="MARKET",
            volume=1.0,
            price=0.0,
            status=OrderStatus.PARTIALLY_FILLED,
            filled_volume=0.5,
            avg_price=2000.0,
        )

        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_volume == 0.5
        assert order.avg_price == 2000.0
        assert order.direction == OrderDirection.SELL
        assert order.order_type == OrderType.MARKET

    def test_create_order_with_custom_times(self) -> None:
        """测试创建带自定义时间的订单."""
        create_time = "2023-12-21T10:00:00.000Z"
        update_time = "2023-12-21T10:30:00.000Z"

        order = UnifiedOrder.create(
            order_id="ORDER003",
            symbol="SOL/USDT",
            direction="BUY",
            order_type="LIMIT",
            volume=10.0,
            price=100.0,
            create_time=create_time,
            update_time=update_time,
        )

        assert order.create_time == create_time
        assert order.update_time == update_time
        assert order.order_type == OrderType.LIMIT

    def test_order_str_method(self) -> None:
        """测试订单的字符串表示."""
        order = UnifiedOrder.create(
            order_id="ORDER004",
            symbol="DOGE/USDT",
            direction="BUY",
            order_type="LIMIT",
            volume=1000.0,
            price=0.5,
        )

        str_repr = str(order)
        assert "UnifiedOrder" in str_repr
        assert "id=ORDER004" in str_repr
        assert "symbol=DOGE/USDT" in str_repr
        assert "BUY 1000.0" in str_repr
        assert "@ 0.5" in str_repr
        assert f"status={OrderStatus.SUBMITTED}" in str_repr


class TestUnifiedOrderMethods:
    """测试统一订单方法."""

    def test_is_completed(self) -> None:
        """测试订单完成判断."""
        # 已完成的订单
        completed_orders = [
            UnifiedOrder.create("O1", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.FILLED),
            UnifiedOrder.create("O2", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.CANCELED),
            UnifiedOrder.create("O3", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.REJECTED),
            UnifiedOrder.create("O4", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.EXPIRED),
        ]

        for order in completed_orders:
            assert order.is_completed() is True

        # 未完成的订单
        active_orders = [
            UnifiedOrder.create("O5", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.SUBMITTED),
            UnifiedOrder.create("O6", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.PARTIALLY_FILLED),
        ]

        for order in active_orders:
            assert order.is_completed() is False

    def test_is_active(self) -> None:
        """测试订单活跃状态判断."""
        # 活跃的订单
        active_orders = [
            UnifiedOrder.create("O7", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.SUBMITTED),
            UnifiedOrder.create("O8", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.PARTIALLY_FILLED),
        ]

        for order in active_orders:
            assert order.is_active() is True

        # 非活跃的订单
        inactive_orders = [
            UnifiedOrder.create("O9", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.FILLED),
            UnifiedOrder.create("O10", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000, status=OrderStatus.CANCELED),
        ]

        for order in inactive_orders:
            assert order.is_active() is False

    def test_remaining_volume(self) -> None:
        """测试获取剩余未成交数量."""
        order = UnifiedOrder.create("O11", "BTC/USDT", "BUY", "LIMIT", 1.0, 30000, filled_volume=0.3)

        assert order.remaining_volume == 0.7

        # 完全成交
        order_filled = UnifiedOrder.create("O12", "BTC/USDT", "BUY", "LIMIT", 0.5, 30000, filled_volume=0.5)
        assert order_filled.remaining_volume == 0.0

        # 超成交（保护）
        order_overfilled = UnifiedOrder.create("O13", "BTC/USDT", "BUY", "LIMIT", 0.5, 30000, filled_volume=0.6)
        assert order_overfilled.remaining_volume == 0.0

    def test_filled_ratio(self) -> None:
        """测试获取成交比例."""
        # 部分成交
        order = UnifiedOrder.create("O14", "BTC/USDT", "BUY", "LIMIT", 1.0, 30000, filled_volume=0.3)
        assert order.filled_ratio == 0.3

        # 完全成交
        order_filled = UnifiedOrder.create("O15", "BTC/USDT", "BUY", "LIMIT", 0.5, 30000, filled_volume=0.5)
        assert order_filled.filled_ratio == 1.0

        # 零成交
        order_zero = UnifiedOrder.create("O16", "BTC/USDT", "BUY", "LIMIT", 1.0, 30000)
        assert order_zero.filled_ratio == 0.0

        # 零委托量（保护）
        order_zero_volume = UnifiedOrder.create("O17", "BTC/USDT", "BUY", "LIMIT", 0.0, 30000)
        assert order_zero_volume.filled_ratio == 0.0

    def test_to_dict(self) -> None:
        """测试转换为字典."""
        order = UnifiedOrder.create("O18", "BTC/USDT", "BUY", "LIMIT", 0.1, 30000)
        order.extra["test_field"] = "test_value"

        order_dict = order.to_dict()
        extra = cast(dict[str, object], order_dict["extra"])
        assert isinstance(order_dict, dict)
        assert order_dict["order_id"] == "O18"
        assert order_dict["symbol"] == "BTC/USDT"
        assert order_dict["direction"] == "BUY"
        # ChannelType 会由 pydantic 自动序列化
        assert "channel_type" in extra
        assert extra["test_field"] == "test_value"


class TestUnifiedOrderTrades:
    """测试订单与成交职责分离."""

    def test_trade_record_keeps_order_link_at_top_level(self) -> None:
        """成交模型应独立携带订单关联键。"""
        trade = TradeRecord.create(
            trade_id="T003",
            symbol="ETHUSDT",
            order_id="ORDER-ETH-1",
            trade_volume=0.3,
            trade_price=2000.0,
        )

        assert trade.symbol == "ETHUSDT"
        assert trade.order_id == "ORDER-ETH-1"


class TestUnifiedOrderChannelSpecific:
    """测试渠道特定功能."""

    def test_external_order_with_specific_fields(self) -> None:
        """测试外部渠道订单特定字段."""
        order = UnifiedOrder.create(
            "B001",
            "BTC/USDT",
            "BUY",
            "LIMIT",
            0.1,
            30000.0,
            channel_type=TradeChannel("external"),
            time_in_force="GTC",
            reduce_only=True,
        )

        assert order.extra["channel_type"] == TradeChannel("external")
        assert order.extra["time_in_force"] == "GTC"
        assert order.extra["reduce_only"] is True

    def test_external_order_with_strategy_fields(self) -> None:
        """测试外部渠道订单的扩展字段."""
        order = UnifiedOrder.create(
            "Q001",
            "000001.SZ",
            "BUY",
            "LIMIT",
            100,
            10.50,
            channel_type=TradeChannel("external"),
            order_source="策略",
            order_kind="限价单",
        )

        assert order.extra["channel_type"] == TradeChannel("external")
        assert order.extra["order_source"] == "策略"
        assert order.extra["order_kind"] == "限价单"

    def test_gm_order_with_specific_fields(self) -> None:
        """测试掘金订单特定字段."""
        order = UnifiedOrder.create(
            "G001",
            "SHFE.ag2401",
            "SELL",
            "LIMIT",
            10,
            5800.0,
            channel_type=TradeChannel.GM,
            strategy_id="STRAT001",
            portfolio_name="TEST_PORT",
        )

        assert order.extra["channel_type"] == TradeChannel.GM
        assert order.extra["strategy_id"] == "STRAT001"
        assert order.extra["portfolio_name"] == "TEST_PORT"

    def test_ctp_order_with_specific_fields(self) -> None:
        """测试CTP订单特定字段."""
        order = UnifiedOrder.create(
            "C001",
            "au2406",
            "BUY",
            "LIMIT",
            1,
            480.0,
            channel_type=TradeChannel.CTP,
            exchange="SHFE",
            investor_id="123456",
            broker_id="9999",
        )

        assert order.extra["channel_type"] == TradeChannel.CTP
        assert order.extra["exchange"] == "SHFE"
        assert order.extra["investor_id"] == "123456"
        assert order.extra["broker_id"] == "9999"

    def test_order_with_raw_data(self) -> None:
        """测试带原始数据的订单."""
        raw_data = {"raw_field": "raw_value", "nested": {"key": "value"}}
        order = UnifiedOrder.create(
            "R001",
            "BTC/USDT",
            "BUY",
            "LIMIT",
            0.1,
            30000.0,
            raw_order_data=raw_data,
        )

        raw_order_data = cast(dict[str, object], order.extra["raw_order_data"])
        assert raw_order_data == raw_data
        assert raw_order_data["raw_field"] == "raw_value"


class TestOrderDirectionAndType:
    """测试订单方向和类型枚举."""

    def test_order_direction_enum(self) -> None:
        """测试订单方向枚举."""
        assert OrderDirection.BUY == "BUY"
        assert OrderDirection.SELL == "SELL"

        # 测试枚举值
        directions = [OrderDirection.BUY, OrderDirection.SELL]
        assert "BUY" in directions
        assert "SELL" in directions

    def test_order_type_enum(self) -> None:
        """测试订单类型枚举."""
        assert OrderType.MARKET == "MARKET"
        assert OrderType.LIMIT == "LIMIT"

        # 测试所有类型
        order_types = [
            OrderType.MARKET,
            OrderType.LIMIT,
        ]
        assert "MARKET" in order_types
        assert "LIMIT" in order_types


class TestUnifiedOrderEdgeCases:
    """测试统一订单边界情况."""

    def test_zero_volume_order(self) -> None:
        """测试零委托量订单."""
        order = UnifiedOrder.create(
            "E001",
            "BTC/USDT",
            "BUY",
            "LIMIT",
            0.0,
            30000.0,
        )

        # 虽然委托量为0，但应该能正常创建
        assert order.volume == 0.0
        assert order.remaining_volume == 0.0
        # 保护：避免除以零
        assert order.filled_ratio == 0.0

    def test_negative_price_order(self) -> None:
        """测试负价格订单（某些特殊场景可能需要）."""
        order = UnifiedOrder.create(
            "E002",
            "TEST/USD",
            "SELL",
            "LIMIT",
            1.0,
            -100.0,  # 负价格（如某些费用或特殊情况）
        )

        assert order.price == -100.0

    @pytest.mark.parametrize(
        ("direction", "order_type"),
        [
            ("BUY", "MARKET"),
            ("BUY", "LIMIT"),
            ("SELL", "MARKET"),
            ("SELL", "LIMIT"),
        ],
    )
    def test_all_direction_and_type_combinations(self, direction: str, order_type: str) -> None:
        """测试所有方向和类型的组合."""
        order = UnifiedOrder.create(
            "E003",
            "TEST/USD",
            direction,
            order_type,
            1.0,
            100.0,
        )

        assert order.direction == direction
        assert order.order_type == order_type


if __name__ == "__main__":
    _ = pytest.main([__file__, "-v"])

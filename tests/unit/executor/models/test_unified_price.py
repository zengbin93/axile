"""
测试 axile.executor.unified_price 模块.

测试统一价格数据模型的功能，包括基础创建、实用方法和价格级别获取。
"""

import pytest

from axile.executor.models.unified_price import UnifiedPriceData, clone_price_data


class TestUnifiedPriceDataCreation:
    """测试统一价格数据创建."""

    def test_basic_creation(self) -> None:
        """测试基础创建."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        assert price.symbol == "BTC/USDT"
        assert price.last_price == 30000.0
        assert price.bid_price == 29999.0
        assert price.ask_price == 30001.0
        assert price.bid_volume == 1.5
        assert price.ask_volume == 1.2
        assert price.volume == 1000.0
        assert price.timestamp == 1703123456789
        assert price.update_time == "2023-12-21T10:30:00.000Z"

    def test_default_values(self) -> None:
        """测试默认值."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        # 默认值应该是0.0
        assert price.bid_price_2 == 0.0
        assert price.bid_price_3 == 0.0
        assert price.bid_price_4 == 0.0
        assert price.bid_price_5 == 0.0
        assert price.ask_price_2 == 0.0
        assert price.ask_price_3 == 0.0
        assert price.ask_price_4 == 0.0
        assert price.ask_price_5 == 0.0
        assert price.bid_volume_2 == 0.0
        assert price.bid_volume_3 == 0.0
        assert price.bid_volume_4 == 0.0
        assert price.bid_volume_5 == 0.0
        assert price.ask_volume_2 == 0.0
        assert price.ask_volume_3 == 0.0
        assert price.ask_volume_4 == 0.0
        assert price.ask_volume_5 == 0.0
        assert price.turnover == 0.0

    def test_str_method(self) -> None:
        """测试__str__方法."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        str_repr = str(price)
        assert "UnifiedPriceData" in str_repr
        assert "symbol=BTC/USDT" in str_repr
        assert "last=30000.0" in str_repr
        assert "bid=29999.0" in str_repr
        assert "ask=30001.0" in str_repr

    def test_extra_field(self) -> None:
        """测试extra字段."""
        extra_data = {"source": "test", "raw_data": {"key": "value"}}
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
            extra=extra_data,
        )

        assert price.extra == extra_data
        assert price.extra["source"] == "test"


class TestUnifiedPriceDataMethods:
    """测试统一价格数据实用方法."""

    def test_get_spread(self) -> None:
        """测试获取价差."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        assert price.get_spread() == 2.0  # 30001.0 - 29999.0

    def test_get_mid_price(self) -> None:
        """测试获取中间价."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        assert price.get_mid_price() == 30000.0  # (29999.0 + 30001.0) / 2

    def test_is_valid(self) -> None:
        """测试数据有效性."""
        valid_price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )
        assert valid_price.is_valid() is True

    def test_to_dict(self) -> None:
        """测试转换为字典."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        price_dict = price.to_dict()
        assert isinstance(price_dict, dict)
        assert price_dict["symbol"] == "BTC/USDT"
        assert price_dict["last_price"] == 30000.0
        assert price_dict["bid_price"] == 29999.0
        assert price_dict["ask_price"] == 30001.0


class TestUnifiedPriceDataPriceLevels:
    """测试价格级别获取方法."""

    def test_get_all_bid_prices(self) -> None:
        """测试获取所有买价."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            bid_price_2=29998.0,
            bid_price_3=29997.0,
            bid_price_4=29996.0,
            bid_price_5=29995.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        bid_prices = price.get_all_bid_prices()
        assert bid_prices == [29999.0, 29998.0, 29997.0, 29996.0, 29995.0]

    def test_get_all_ask_prices(self) -> None:
        """测试获取所有卖价."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            ask_price_2=30002.0,
            ask_price_3=30003.0,
            ask_price_4=30004.0,
            ask_price_5=30005.0,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        ask_prices = price.get_all_ask_prices()
        assert ask_prices == [30001.0, 30002.0, 30003.0, 30004.0, 30005.0]

    def test_get_all_bid_volumes(self) -> None:
        """测试获取所有买量."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            bid_volume_2=2.0,
            bid_volume_3=1.8,
            bid_volume_4=2.2,
            bid_volume_5=1.9,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        bid_volumes = price.get_all_bid_volumes()
        assert bid_volumes == [1.5, 2.0, 1.8, 2.2, 1.9]

    def test_get_all_ask_volumes(self) -> None:
        """测试获取所有卖量."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            ask_price=30001.0,
            bid_volume=1.5,
            ask_volume=1.2,
            ask_volume_2=1.6,
            ask_volume_3=2.1,
            ask_volume_4=1.7,
            ask_volume_5=2.3,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        ask_volumes = price.get_all_ask_volumes()
        assert ask_volumes == [1.2, 1.6, 2.1, 1.7, 2.3]

    def test_get_price_levels(self) -> None:
        """测试获取指定深度的价格."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            bid_price_2=29998.0,
            bid_price_3=29997.0,
            bid_price_4=29996.0,
            bid_price_5=29995.0,
            ask_price=30001.0,
            ask_price_2=30002.0,
            ask_price_3=30003.0,
            ask_price_4=30004.0,
            ask_price_5=30005.0,
            bid_volume=1.5,
            bid_volume_2=2.0,
            bid_volume_3=1.8,
            bid_volume_4=2.2,
            bid_volume_5=1.9,
            ask_volume=1.2,
            ask_volume_2=1.6,
            ask_volume_3=2.1,
            ask_volume_4=1.7,
            ask_volume_5=2.3,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        # 测试获取3档
        levels_3 = price.get_price_levels(3)
        assert levels_3["bid_prices"] == [29999.0, 29998.0, 29997.0]
        assert levels_3["ask_prices"] == [30001.0, 30002.0, 30003.0]
        assert levels_3["bid_volumes"] == [1.5, 2.0, 1.8]
        assert levels_3["ask_volumes"] == [1.2, 1.6, 2.1]

    @pytest.mark.parametrize("depth", [0, -1, 6, 10])
    def test_get_price_levels_edge_cases(self, depth: int) -> None:
        """测试获取指定深度的边界情况."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=30000.0,
            bid_price=29999.0,
            bid_price_2=29998.0,
            bid_price_3=29997.0,
            bid_price_4=29996.0,
            bid_price_5=29995.0,
            ask_price=30001.0,
            ask_price_2=30002.0,
            ask_price_3=30003.0,
            ask_price_4=30004.0,
            ask_price_5=30005.0,
            bid_volume=1.5,
            bid_volume_2=2.0,
            bid_volume_3=1.8,
            bid_volume_4=2.2,
            bid_volume_5=1.9,
            ask_volume=1.2,
            ask_volume_2=1.6,
            ask_volume_3=2.1,
            ask_volume_4=1.7,
            ask_volume_5=2.3,
            volume=1000.0,
            timestamp=1703123456789,
            update_time="2023-12-21T10:30:00.000Z",
        )

        levels = price.get_price_levels(depth)

        # 无论输入什么depth，都应该返回有效的数据
        assert "bid_prices" in levels
        assert "ask_prices" in levels
        assert "bid_volumes" in levels
        assert "ask_volumes" in levels

        # 深度应该被限制在1-5之间
        assert len(levels["bid_prices"]) >= 1
        assert len(levels["bid_prices"]) <= 5
        assert len(levels["ask_prices"]) >= 1
        assert len(levels["ask_prices"]) <= 5


class TestUnifiedPriceDataValidation:
    """测试统一价格数据验证."""

    @pytest.mark.parametrize(
        ("last_price", "bid_price", "ask_price", "timestamp", "expected"),
        [
            # 有效数据
            (30000.0, 29999.0, 30001.0, 1703123456789, True),
            # 无效数据：负数价格
            (-30000.0, 29999.0, 30001.0, 1703123456789, False),
            (30000.0, -29999.0, 30001.0, 1703123456789, False),
            (30000.0, 29999.0, -30001.0, 1703123456789, False),
            # 无效数据：买价大于卖价
            (30000.0, 30001.0, 29999.0, 1703123456789, False),
            # 无效数据：零时间戳
            (30000.0, 29999.0, 30001.0, 0, False),
            # 无效数据：零价格
            (0.0, 29999.0, 30001.0, 1703123456789, False),
            (30000.0, 0.0, 30001.0, 1703123456789, False),
            (30000.0, 29999.0, 0.0, 1703123456789, False),
        ],
    )
    def test_is_valid_edge_cases(
        self, last_price: float, bid_price: float, ask_price: float, timestamp: int, expected: bool
    ) -> None:
        """测试数据有效性的边界情况."""
        price = UnifiedPriceData(
            symbol="BTC/USDT",
            last_price=last_price,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_volume=1.5,
            ask_volume=1.2,
            volume=1000.0,
            timestamp=timestamp,
            update_time="2023-12-21T10:30:00.000Z",
        )

        assert price.is_valid() is expected


def test_book_valid_defaults_true_and_survives_clone() -> None:
    """book_valid 默认 True，且经 clone_price_data 深拷贝后保留."""
    price = UnifiedPriceData(
        symbol="BTC/USDT",
        last_price=30000.0,
        bid_price=29999.0,
        ask_price=30001.0,
        bid_volume=1.5,
        ask_volume=1.2,
        volume=1000.0,
        timestamp=1,
        update_time="2023-12-21T10:30:00.000Z",
    )
    assert price.book_valid is True

    invalid = price.model_copy(update={"book_valid": False})
    assert invalid.book_valid is False
    assert clone_price_data(invalid).book_valid is False


if __name__ == "__main__":
    _ = pytest.main([__file__, "-v"])

"""
测试 axile.executor.unified_model 模块.

测试统一账户资产数据模型的功能，包括持仓和账户资产的创建、管理和验证。
"""

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_account_assets import (
    Position,
    PositionDirection,
    UnifiedAccountAssets,
)


class TestPositionDirection:
    """测试持仓方向枚举."""

    def test_position_direction_enum(self) -> None:
        """测试持仓方向枚举值."""
        assert PositionDirection.LONG == "多头"
        assert PositionDirection.SHORT == "空头"
        assert PositionDirection.NET == "净"

        # 测试枚举值
        directions = [PositionDirection.LONG, PositionDirection.SHORT, PositionDirection.NET]
        assert "多头" in directions
        assert "空头" in directions
        assert "净" in directions


class TestPosition:
    """测试持仓数据模型."""

    def test_create_position(self) -> None:
        """测试创建持仓."""
        position = Position(
            symbol="rb2610",
            volume=0.1,
            available_volume=0.1,
            market_value=3000.0,
            direction=PositionDirection.LONG,
            avg_price=30000.0,
        )

        assert position.symbol == "rb2610"
        assert position.volume == 0.1
        assert position.available_volume == 0.1
        assert position.market_value == 3000.0
        assert position.direction == "多头"  # use_enum_values=True
        assert position.avg_price == 30000.0

    def test_create_position_without_avg_price(self) -> None:
        """测试创建没有成本价的持仓."""
        position = Position(
            symbol="ag2612",
            volume=1.0,
            available_volume=1.0,
            market_value=2000.0,
            direction=PositionDirection.SHORT,
            avg_price=None,
        )

        assert position.symbol == "ag2612"
        assert position.direction == "空头"
        assert position.avg_price is None

    def test_position_str_method(self) -> None:
        """测试持仓的字符串表示."""
        position = Position(
            symbol="cu2610",
            volume=1000.0,
            available_volume=1000.0,
            market_value=500.0,
            direction=PositionDirection.LONG,
            avg_price=0.5,
        )

        str_repr = str(position)
        assert "Position" in str_repr
        assert "symbol=cu2610" in str_repr
        assert "volume=1000.0" in str_repr
        assert "direction=多头" in str_repr

    def test_position_extra_field(self) -> None:
        """测试持仓的额外字段."""
        extra_data = {"source": "exchange", "leverage": 2.0}
        position = Position(
            symbol="au2612",
            volume=10.0,
            available_volume=10.0,
            market_value=1000.0,
            direction=PositionDirection.LONG,
            avg_price=100.0,
            extra=extra_data,
        )

        assert position.extra == extra_data
        assert position.extra["source"] == "exchange"
        assert position.extra["leverage"] == 2.0

    @pytest.mark.parametrize(
        "direction",
        [PositionDirection.LONG, PositionDirection.SHORT, PositionDirection.NET],
    )
    def test_position_all_directions(self, direction: PositionDirection) -> None:
        """测试所有持仓方向."""
        position = Position(
            symbol="TEST/USD",
            volume=1.0,
            available_volume=1.0,
            market_value=100.0,
            direction=direction,
            avg_price=None,
        )

        assert position.direction == direction


class TestUnifiedAccountAssets:
    """测试统一账户资产模型."""

    def test_create_basic_assets(self) -> None:
        """测试创建基础账户资产."""
        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.0,
            market_value=5000.0,
            positions=[],
        )

        assert assets.available_cash == 10000.0
        assert assets.total_asset == 15000.0
        assert assets.market_value == 5000.0
        assert len(assets.positions) == 0
        assert assets.currency == "CNY"  # 默认值
        assert assets.update_time is not None

    def test_create_assets_with_positions(self) -> None:
        """测试创建带持仓的账户资产."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.1,
                available_volume=0.1,
                market_value=3000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
        ]

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.0,
            market_value=5000.0,
            positions=positions,
        )

        assert len(assets.positions) == 2
        assert assets.positions[0].symbol == "rb2610"
        assert assets.positions[1].symbol == "ag2612"

    def test_assets_str_method(self) -> None:
        """测试账户资产的字符串表示."""
        assets = UnifiedAccountAssets(
            available_cash=10000.50,
            total_asset=15000.75,
            market_value=5000.25,
            positions=[],
        )

        str_repr = str(assets)
        assert "AccountAssets" in str_repr
        assert "cash=10000.50" in str_repr
        assert "total=15000.75" in str_repr
        assert "positions=0" in str_repr

    def test_assets_extra_field(self) -> None:
        """测试账户资产的额外字段."""
        extra_data = {"channel": "external", "account_type": "margin"}
        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.0,
            market_value=5000.0,
            positions=[],
            currency="USD",
            extra=extra_data,
        )

        assert assets.currency == "USD"
        assert assets.extra == extra_data
        assert assets.extra["channel"] == "external"
        assert assets.extra["account_type"] == "margin"


class TestUnifiedAccountAssetsMethods:
    """测试统一账户资产方法."""

    def test_get_position(self) -> None:
        """测试获取持仓."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.1,
                available_volume=0.1,
                market_value=3000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
        ]

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.0,
            market_value=5000.0,
            positions=positions,
        )

        # 获取存在的持仓
        rb_pos = assets.get_position("rb2610")
        assert rb_pos is not None
        assert rb_pos.symbol == "rb2610"
        assert rb_pos.volume == 0.1

        ag_pos = assets.get_position("ag2612")
        assert ag_pos is not None
        assert ag_pos.symbol == "ag2612"

        # 获取不存在的持仓
        au_pos = assets.get_position("au2612")
        assert au_pos is None

    def test_get_total_position_value(self) -> None:
        """测试计算总持仓市值."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.1,
                available_volume=0.1,
                market_value=3000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
            Position(
                symbol="cu2610",
                volume=1000.0,
                available_volume=1000.0,
                market_value=500.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            ),
        ]

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15500.0,
            market_value=5500.0,
            positions=positions,
        )

        total_value = assets.get_total_position_value()
        assert total_value == 5500.0  # 3000 + 2000 + 500

    def test_validate_balance(self) -> None:
        """测试验证账户平衡."""
        # 平衡的情况
        balanced_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.0,
            market_value=5000.0,
            positions=[],
        )
        assert balanced_assets.validate_balance() is True

        # 在误差范围内的情况
        tolerance_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.005,  # 0.005的误差
            market_value=5000.0,
            positions=[],
        )
        assert tolerance_assets.validate_balance() is True

        # 不平衡的情况
        unbalanced_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=16000.0,  # 1000的误差
            market_value=5000.0,
            positions=[],
        )
        assert unbalanced_assets.validate_balance() is False

    def test_validate_balance_with_positions(self) -> None:
        """测试带持仓的账户平衡验证."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.1,
                available_volume=0.1,
                market_value=3000.0,
                direction=PositionDirection.LONG,
                avg_price=None,
            )
        ]

        # 正确的平衡
        correct_assets = UnifiedAccountAssets(
            available_cash=7000.0,
            total_asset=10000.0,
            market_value=3000.0,
            positions=positions,
        )
        assert correct_assets.validate_balance() is True

        # 计算的总市值与实际不符
        incorrect_assets = UnifiedAccountAssets(
            available_cash=7000.0,
            total_asset=10000.0,
            market_value=3100.0,  # 与实际总市值不符
            positions=positions,
        )
        # 注意：validate_balance检查的是market_value字段，而不是重新计算
        # 所以这里7000 + 3100 = 10100 != 10000，返回False
        assert incorrect_assets.validate_balance() is False


class TestUnifiedAccountAssetsCreate:
    """测试统一账户资产工厂方法."""

    def test_create_with_positions_data(self) -> None:
        """测试使用持仓数据创建账户资产."""
        positions_data = [
            {
                "symbol": "rb2610",
                "volume": 0.1,
                "available_volume": 0.1,
                "market_value": 3000.0,
                "direction": "多头",
                "avg_price": 30000.0,
            },
            {
                "symbol": "ag2612",
                "volume": 2.0,
                "available_volume": 2.0,
                "market_value": 2000.0,
                "direction": "多头",
            },
        ]

        assets = UnifiedAccountAssets.create(
            available_cash=10000.0,
            total_asset=15000.0,
            positions_data=positions_data,
            channel_type=TradeChannel("external"),
        )

        # 验证基本字段
        assert assets.available_cash == 10000.0
        assert assets.total_asset == 15000.0
        assert assets.currency == "CNY"
        assert assets.extra["channel_type"] == TradeChannel("external")

        # 验证持仓
        assert len(assets.positions) == 2
        assert assets.positions[0].symbol == "rb2610"
        assert assets.positions[0].volume == 0.1
        assert assets.positions[0].avg_price == 30000.0
        assert assets.positions[0].extra["channel_type"] == TradeChannel("external")

        assert assets.positions[1].symbol == "ag2612"
        assert assets.positions[1].volume == 2.0
        assert assets.positions[1].avg_price is None

    def test_create_with_int_volume(self) -> None:
        """测试创建时将整数体积转换为浮点数."""
        positions_data = [
            {
                "symbol": "000001.SZ",
                "volume": 100,  # 整数
                "available_volume": 100,  # 整数
                "market_value": 1050.0,
                "direction": "多头",
                "avg_price": 10.5,
            }
        ]

        assets = UnifiedAccountAssets.create(
            available_cash=5000.0,
            total_asset=6050.0,
            positions_data=positions_data,
            channel_type=TradeChannel("external"),
        )

        position = assets.positions[0]
        assert isinstance(position.volume, float)
        assert position.volume == 100.0
        assert isinstance(position.available_volume, float)
        assert position.available_volume == 100.0

    def test_create_with_different_channel_types(self) -> None:
        """测试创建不同渠道类型的账户资产."""
        positions_data = [
            {
                "symbol": "TEST",
                "volume": 1.0,
                "available_volume": 1.0,
                "market_value": 1000.0,
                "direction": "多头",
            }
        ]

        # 测试不同渠道
        channels = [
            TradeChannel("external"),
            TradeChannel.GM,
            TradeChannel.CTP,
        ]

        for channel in channels:
            assets = UnifiedAccountAssets.create(
                available_cash=5000.0,
                total_asset=6000.0,
                positions_data=positions_data,
                channel_type=channel,
                currency="USD",
            )

            assert assets.currency == "USD"
            assert assets.extra["channel_type"] == channel
            assert assets.positions[0].extra["channel_type"] == channel

    def test_create_with_empty_positions(self) -> None:
        """测试创建空持仓的账户资产."""
        assets = UnifiedAccountAssets.create(
            available_cash=10000.0,
            total_asset=10000.0,
            positions_data=[],
            channel_type=TradeChannel("external"),
        )

        assert len(assets.positions) == 0
        assert assets.market_value == 0.0
        assert assets.validate_balance() is True

    def test_create_with_extra_in_position_data(self) -> None:
        """测试创建时持仓数据中的额外字段."""
        positions_data = [
            {
                "symbol": "rb2610",
                "volume": 0.1,
                "available_volume": 0.1,
                "market_value": 3000.0,
                "direction": "多头",
                "extra": {
                    "leverage": 2.0,
                    "margin_mode": "cross",
                },
            }
        ]

        assets = UnifiedAccountAssets.create(
            available_cash=7000.0,
            total_asset=10000.0,
            positions_data=positions_data,
            channel_type=TradeChannel("external"),
        )

        position = assets.positions[0]
        assert position.extra["leverage"] == 2.0
        assert position.extra["margin_mode"] == "cross"
        assert position.extra["channel_type"] == TradeChannel("external")

    @pytest.mark.parametrize("direction", ["多头", "空头", "净"])
    def test_create_with_all_directions(self, direction: str) -> None:
        """测试创建所有方向的持仓."""
        positions_data: list[dict[str, str | float]] = [
            {
                "symbol": "TEST/USD",
                "volume": 1.0,
                "available_volume": 1.0,
                "market_value": 1000.0,
                "direction": direction,
            }
        ]

        assets = UnifiedAccountAssets.create(
            available_cash=5000.0,
            total_asset=6000.0,
            positions_data=positions_data,
            channel_type=TradeChannel("external"),
        )

        assert assets.positions[0].direction == direction


class TestUnifiedModelEdgeCases:
    """测试统一模型边界情况."""

    def test_zero_values(self) -> None:
        """测试零值."""
        assets = UnifiedAccountAssets(
            available_cash=0.0,
            total_asset=0.0,
            market_value=0.0,
            positions=[],
        )

        assert assets.validate_balance() is True
        assert assets.get_total_position_value() == 0.0

    def test_negative_cash(self) -> None:
        """测试负可用资金（如融资账户）."""
        assets = UnifiedAccountAssets(
            available_cash=-1000.0,  # 负资金（借钱）
            total_asset=4000.0,
            market_value=5000.0,
            positions=[],
        )

        assert assets.validate_balance() is True  # -1000 + 5000 = 4000

    def test_large_numbers(self) -> None:
        """测试大数值."""
        assets = UnifiedAccountAssets(
            available_cash=1_000_000_000.0,
            total_asset=2_000_000_000.0,
            market_value=1_000_000_000.0,
            positions=[],
        )

        assert assets.validate_balance() is True

    def test_many_positions(self) -> None:
        """测试大量持仓."""
        positions: list[Position] = []
        for i in range(100):
            positions.append(
                Position(
                    symbol=f"TEST{i}/USD",
                    volume=1.0,
                    available_volume=1.0,
                    market_value=100.0,
                    direction=PositionDirection.LONG,
                    avg_price=None,
                )
            )

        assets = UnifiedAccountAssets(
            available_cash=0.0,
            total_asset=10000.0,
            market_value=10000.0,
            positions=positions,
        )

        assert len(assets.positions) == 100
        assert assets.get_total_position_value() == 10000.0


if __name__ == "__main__":
    _ = pytest.main([__file__, "-v"])

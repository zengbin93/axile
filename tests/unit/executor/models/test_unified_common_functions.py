"""
测试 UnifiedAccountAssets.update_curr_target 方法.

测试基于Pydantic AccountAssets模型的目标仓位更新方法。
"""

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_account_assets import (
    Position,
    PositionDirection,
    UnifiedAccountAssets,
)


class TestUnifiedUpdateCurrTarget:
    """测试统一目标仓位更新方法."""

    def test_basic_functionality(self) -> None:
        """测试基本功能."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=2000.0,
            ),
            Position(
                symbol="cu2610",
                volume=1000.0,
                available_volume=1000.0,
                market_value=500.0,
                direction=PositionDirection.LONG,
                avg_price=0.5,
            ),
        ]

        account_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=27500.0,
            market_value=17500.0,
            positions=positions,
        )

        curr_target: dict[str, float] = {"rb2610": 0.1, "ag2612": 0.2}

        result = account_assets.update_curr_target(curr_target)

        # 应该包含持仓中不在目标中的品种，权重为0
        expected = {"rb2610": 0.1, "ag2612": 0.2, "cu2610": 0.0}
        assert result == expected

    def test_forbidden_symbols(self) -> None:
        """测试禁止交易品种过滤."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=2000.0,
            ),
            Position(
                symbol="cu2610",
                volume=1000.0,
                available_volume=1000.0,
                market_value=500.0,
                direction=PositionDirection.LONG,
                avg_price=0.5,
            ),
        ]

        account_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=27500.0,
            market_value=17500.0,
            positions=positions,
        )

        curr_target = {"rb2610": 0.1, "ag2612": 0.2, "cu2610": 0.05}
        forbidden_symbols = ["cu2610", "IF2609"]

        result = account_assets.update_curr_target(curr_target, forbidden_symbols=forbidden_symbols)

        # 禁止品种应被过滤掉
        expected = {"rb2610": 0.1, "ag2612": 0.2}
        assert result == expected

    def test_risk_symbols(self) -> None:
        """测试风险品种自动清零."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=2000.0,
            ),
            Position(
                symbol="cu2610",
                volume=1000.0,
                available_volume=1000.0,
                market_value=500.0,
                direction=PositionDirection.LONG,
                avg_price=0.5,
            ),
        ]

        account_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=27500.0,
            market_value=17500.0,
            positions=positions,
        )

        curr_target = {"rb2610": 0.1, "ag2612": 0.2, "cu2610": 0.05}
        risk_symbols = ["cu2610"]

        result = account_assets.update_curr_target(curr_target, risk_symbols=risk_symbols)

        # 风险品种应被设置为0
        expected = {"rb2610": 0.1, "ag2612": 0.2, "cu2610": 0.0}
        assert result == expected

    def test_empty_positions(self) -> None:
        """测试空持仓."""
        empty_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=10000.0,
            market_value=0.0,
            positions=[],
        )
        curr_target: dict[str, float] = {"rb2610": 0.1, "ag2612": 0.2}

        result = empty_assets.update_curr_target(curr_target)

        expected = {"rb2610": 0.1, "ag2612": 0.2}
        assert result == expected

    def test_none_target(self) -> None:
        """测试None目标输入."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            ),
            Position(
                symbol="ag2612",
                volume=1.0,
                available_volume=1.0,
                market_value=2000.0,
                direction=PositionDirection.LONG,
                avg_price=2000.0,
            ),
        ]

        account_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=17000.0,
            market_value=7000.0,
            positions=positions,
        )

        # 现在方法支持None输入，会自动补充持仓中的品种但权重为0
        result = account_assets.update_curr_target(None)
        expected = {"rb2610": 0.0, "ag2612": 0.0}
        assert result == expected

    def test_empty_inputs(self) -> None:
        """测试空输入."""
        empty_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=10000.0,
            market_value=0.0,
            positions=[],
        )
        result = empty_assets.update_curr_target({})
        assert result == {}

    def test_symbol_not_in_positions(self) -> None:
        """测试目标中的品种不在持仓中."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            ),
        ]

        account_assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=15000.0,
            market_value=15000.0,
            positions=positions,
        )

        curr_target = {"rb2610": 0.1, "ag2612": 0.2}

        result = account_assets.update_curr_target(curr_target)

        # ag2612 不在持仓中，应被添加为 0 权重，但保留原有的权重值
        expected = {"rb2610": 0.1, "ag2612": 0.2}
        assert result == expected

    @pytest.mark.parametrize(
        ("curr_target", "account_assets", "expected"),
        [
            # 基本测试
            (
                {"rb2610": 0.1},
                UnifiedAccountAssets(
                    available_cash=10000.0,
                    total_asset=15000.0,
                    market_value=5000.0,
                    positions=[
                        Position(
                            symbol="rb2610",
                            volume=0.5,
                            available_volume=0.5,
                            market_value=5000.0,
                            direction=PositionDirection.LONG,
                            avg_price=10000.0,
                        )
                    ],
                ),
                {"rb2610": 0.1},
            ),
            # 空持仓
            (
                {"rb2610": 0.1},
                UnifiedAccountAssets(
                    available_cash=10000.0,
                    total_asset=10000.0,
                    market_value=0.0,
                    positions=[],
                ),
                {"rb2610": 0.1},
            ),
            # 空目标
            (
                {},
                UnifiedAccountAssets(
                    available_cash=10000.0,
                    total_asset=15000.0,
                    market_value=5000.0,
                    positions=[
                        Position(
                            symbol="rb2610",
                            volume=0.5,
                            available_volume=0.5,
                            market_value=5000.0,
                            direction=PositionDirection.LONG,
                            avg_price=10000.0,
                        )
                    ],
                ),
                {"rb2610": 0.0},
            ),
        ],
    )
    def test_parameterized_cases(
        self,
        curr_target: dict[str, float],
        account_assets: UnifiedAccountAssets,
        expected: dict[str, float],
    ) -> None:
        """参数化测试."""
        result = account_assets.update_curr_target(curr_target)
        assert result == expected


class TestPydanticIntegration:
    """测试Pydantic模型集成."""

    def test_account_assets_validation(self) -> None:
        """测试AccountAssets模型验证."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            )
        ]

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=25000.0,
            market_value=15000.0,
            positions=positions,
            currency="USD",
        )

        # 测试模型属性访问
        assert assets.available_cash == 10000.0
        assert assets.total_asset == 25000.0
        assert assets.currency == "USD"
        assert len(assets.positions) == 1

    def test_position_validation(self) -> None:
        """测试Position模型验证."""
        position = Position(
            symbol="rb2610",
            volume=0.5,
            available_volume=0.5,
            market_value=15000.0,
            direction=PositionDirection.LONG,
            avg_price=30000.0,
        )

        # 测试模型属性访问
        assert position.symbol == "rb2610"
        assert position.volume == 0.5
        assert position.direction == PositionDirection.LONG
        assert position.avg_price == 30000.0

    def test_position_direction_enum(self) -> None:
        """测试PositionDirection枚举."""
        # 测试不同的方向枚举值
        long_pos = Position(
            symbol="rb2610",
            volume=0.5,
            available_volume=0.5,
            market_value=15000.0,
            direction=PositionDirection.LONG,
            avg_price=30000.0,
        )

        short_pos = Position(
            symbol="ag2612",
            volume=1.0,
            available_volume=1.0,
            market_value=2000.0,
            direction=PositionDirection.SHORT,
            avg_price=2000.0,
        )

        # PositionDirection 继承自 str，因此其值本身就是字符串
        assert long_pos.direction == "多头"
        assert short_pos.direction == "空头"

    def test_account_assets_factory(self) -> None:
        """测试AccountAssets create方法."""
        # 测试使用create方法创建AccountAssets
        assets = UnifiedAccountAssets.create(
            available_cash=10000.0,
            total_asset=27500.0,
            positions_data=[
                {
                    "symbol": "rb2610",
                    "volume": 0.5,
                    "available_volume": 0.5,
                    "market_value": 15000.0,
                    "direction": "多头",
                    "avg_price": 30000.0,
                },
                {
                    "symbol": "ag2612",
                    "volume": 1.0,
                    "available_volume": 1.0,
                    "market_value": 2000.0,
                    "direction": "多头",
                    "avg_price": 2000.0,
                },
            ],
            channel_type=TradeChannel("external"),
        )

        assert len(assets.positions) == 2
        assert assets.positions[0].symbol == "rb2610"
        assert assets.positions[1].direction == PositionDirection.LONG
        assert assets.extra.get("channel_type") == TradeChannel("external")

    def test_model_serialization(self) -> None:
        """测试模型序列化."""
        position = Position(
            symbol="rb2610",
            volume=0.5,
            available_volume=0.5,
            market_value=15000.0,
            direction=PositionDirection.LONG,
            avg_price=30000.0,
        )

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=25000.0,
            market_value=15000.0,
            positions=[position],
        )

        # 测试序列化为字典
        assets_dict = assets.model_dump()
        assert isinstance(assets_dict, dict)
        assert "positions" in assets_dict
        assert assets_dict["available_cash"] == 10000.0

        # 测试JSON序列化
        assets_json = assets.model_dump_json()
        assert isinstance(assets_json, str)
        assert "rb2610" in assets_json


class TestIntegration:
    """集成测试."""

    def test_complete_workflow(self) -> None:
        """测试完整工作流程."""
        # 1. 定义目标权重
        curr_target = {"rb2610": 0.1, "ag2612": 0.2}

        # 2. 创建账户资产（使用工厂方法）
        assets = UnifiedAccountAssets.create(
            available_cash=10000.0,
            total_asset=27500.0,
            positions_data=[
                {
                    "symbol": "rb2610",
                    "volume": 0.5,
                    "available_volume": 0.5,
                    "market_value": 15000.0,
                    "direction": "多头",
                    "avg_price": 30000.0,
                },
                {
                    "symbol": "ag2612",
                    "volume": 1.0,
                    "available_volume": 1.0,
                    "market_value": 2000.0,
                    "direction": "多头",
                    "avg_price": 2000.0,
                },
                {
                    "symbol": "cu2610",
                    "volume": 1000,
                    "available_volume": 1000,
                    "market_value": 500,
                    "direction": "多头",
                    "avg_price": 0.5,
                },
            ],
            channel_type=TradeChannel("external"),
        )

        # 3. 更新目标权重
        updated_target = assets.update_curr_target(curr_target, forbidden_symbols=["IF2609"], risk_symbols=["cu2610"])

        # 验证结果
        assert "rb2610" in updated_target
        assert "ag2612" in updated_target
        assert isinstance(updated_target, dict)

        # 验证自动补充的品种权重为0
        assert updated_target["cu2610"] == 0.0

        # 验证原有目标权重保持不变
        assert updated_target["rb2610"] == 0.1
        assert updated_target["ag2612"] == 0.2

        # 验证模型属性
        assert assets.currency == "CNY"
        assert assets.extra.get("channel_type") == TradeChannel("external")

    def test_validation_methods(self) -> None:
        """测试验证方法."""
        positions = [
            Position(
                symbol="rb2610",
                volume=0.5,
                available_volume=0.5,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=30000.0,
            )
        ]

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=25000.0,
            market_value=15000.0,
            positions=positions,
        )

        # 测试模型的内置验证方法
        assert assets.validate_balance()  # 10000 + 15000 = 25000

        # 测试获取持仓
        rb_position = assets.get_position("rb2610")
        assert rb_position is not None
        assert rb_position.symbol == "rb2610"

        # 测试获取总持仓市值
        total_value = assets.get_total_position_value()
        assert total_value == 15000.0

    def test_edge_cases(self) -> None:
        """测试边界情况."""
        # 测试所有方向枚举值
        all_directions = [
            Position(
                symbol="rb2610",
                volume=0.1,
                available_volume=0.1,
                market_value=1000,
                direction=PositionDirection.LONG,
                avg_price=10000,
            ),
            Position(
                symbol="ag2612",
                volume=0.1,
                available_volume=0.1,
                market_value=1000,
                direction=PositionDirection.SHORT,
                avg_price=10000,
            ),
            Position(
                symbol="au2612",
                volume=0.1,
                available_volume=0.1,
                market_value=1000,
                direction=PositionDirection.NET,
                avg_price=10000,
            ),
        ]

        assets = UnifiedAccountAssets(
            available_cash=10000.0,
            total_asset=13000.0,
            market_value=3000.0,
            positions=all_directions,
        )

        curr_target = {"rb2610": 0.1}
        result = assets.update_curr_target(curr_target)

        # 验证所有方向的品种都被正确处理
        assert "rb2610" in result
        assert "ag2612" in result
        assert "au2612" in result
        assert result["ag2612"] == 0.0
        assert result["au2612"] == 0.0


if __name__ == "__main__":
    _ = pytest.main([__file__, "-v"])

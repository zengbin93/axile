"""``CTPExecutor._calculate_generic_volume`` 单测.

通过直接调用 ``CTPExecutor._calculate_generic_volume`` 验证计算口径，
不触发 CTP 连接初始化。覆盖的场景:

- 期货: ``total_asset × weight / (price × VolumeMultiple)`` 公式 + 取整
- 期权 ``sizing_mode='premium_weight'``: 与期货同公式（默认）
- 期权 ``sizing_mode='lots'``: 直接当目标手数
- 异常分支: 价格非法、合约缓存缺失
- ``trade_rule.contract_multiplier`` 兜底路径
"""

from __future__ import annotations

from typing import cast

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.ctp.core.objects import InstrumentField
from axile.executor.ctp.ctp_execute import CTPExecutor
from axile.executor.models.unified_account_assets import UnifiedAccountAssets


class _StubTrader:
    """最小 trader 双件，只暴露 ``instruments`` 字典。"""

    def __init__(self, instruments: dict[str, InstrumentField] | None = None) -> None:
        self.instruments: dict[str, InstrumentField] = instruments or {}


def _make_executor(instruments: dict[str, InstrumentField] | None = None) -> CTPExecutor:
    """构造未连接的 CTPExecutor，只挂上桩 trader。"""
    executor = CTPExecutor.__new__(CTPExecutor)
    # _calculate_generic_volume 仅依赖 self.trader.instruments；其它属性可省略。
    executor.trader = cast(object, _StubTrader(instruments))  # type: ignore[assignment]
    executor.channel_type = TradeChannel.CTP
    return executor


def _account(total_asset: float = 100_000.0) -> UnifiedAccountAssets:
    return UnifiedAccountAssets(
        available_cash=total_asset,
        total_asset=total_asset,
        market_value=0.0,
        positions=[],
    )


@pytest.fixture
def m2510_call() -> InstrumentField:
    """豆粕看涨期权样例。"""
    return InstrumentField(
        InstrumentID="m2510-C-3100",
        ProductClass="2",
        OptionsType="1",
        StrikePrice=3100.0,
        UnderlyingInstrID="m2510",
        UnderlyingMultiple=10.0,
        ExpireDate="20251015",
        VolumeMultiple=10,
    )


@pytest.fixture
def rb_future() -> InstrumentField:
    """螺纹钢期货样例。"""
    return InstrumentField(InstrumentID="rb2510", ProductClass="1", VolumeMultiple=10)


class TestFutureWeightFormula:
    """期货 weight 公式：``total_asset × weight / (price × VolumeMultiple)``。"""

    def test_basic_formula(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.2,
            price=4000.0,
            account_assets=_account(1_000_000.0),
            trade_rule={},
            symbol="rb2510",
        )
        # 1_000_000 × 0.2 / (4000 × 10) = 5
        assert result == 5.0

    def test_zero_weight_returns_zero(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.0,
            price=4000.0,
            account_assets=_account(),
            trade_rule={},
            symbol="rb2510",
        )
        assert result == 0.0

    def test_negative_weight_supported(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=-0.1,
            price=4000.0,
            account_assets=_account(800_000.0),
            trade_rule={},
            symbol="rb2510",
        )
        # 800_000 × -0.1 / (4000 × 10) = -2
        assert result == -2.0


class TestPriceAndMultiplierEdgeCases:
    """价格 / 合约乘数异常分支必须返回 0."""

    def test_zero_price_returns_zero(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.2,
            price=0.0,
            account_assets=_account(),
            trade_rule={},
            symbol="rb2510",
        )
        assert result == 0.0

    def test_negative_price_returns_zero(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.2,
            price=-1.0,
            account_assets=_account(),
            trade_rule={},
            symbol="rb2510",
        )
        assert result == 0.0

    def test_missing_instrument_and_no_fallback_returns_zero(self) -> None:
        executor = _make_executor({})
        result = executor._calculate_generic_volume(
            weight=0.2,
            price=4000.0,
            account_assets=_account(),
            trade_rule={},
            symbol="unknown",
        )
        assert result == 0.0

    def test_contract_multiplier_fallback(self) -> None:
        """缓存缺失时通过 trade_rule.contract_multiplier 兜底。"""
        executor = _make_executor({})
        result = executor._calculate_generic_volume(
            weight=0.2,
            price=4000.0,
            account_assets=_account(1_000_000.0),
            trade_rule={"contract_multiplier": 10},
            symbol="rb2510",
        )
        assert result == 5.0


class TestSizingModeLots:
    """``sizing_mode='lots'`` 直接把 weight 当目标手数。"""

    def test_lots_mode_returns_weight_as_volume(self) -> None:
        executor = _make_executor({})
        result = executor._calculate_generic_volume(
            weight=5,
            price=3100.0,
            account_assets=_account(),
            trade_rule={"sizing_mode": "lots"},
            symbol="m2510-C-3100",
        )
        assert result == 5.0

    def test_lots_mode_supports_negative(self) -> None:
        executor = _make_executor({})
        result = executor._calculate_generic_volume(
            weight=-3,
            price=2900.0,
            account_assets=_account(),
            trade_rule={"sizing_mode": "lots"},
            symbol="m2510-P-2900",
        )
        assert result == -3.0

    def test_lots_mode_skips_volume_multiple_lookup(self, m2510_call: InstrumentField) -> None:
        """lots 模式不应触碰合约缓存，即便有合约也不应改变结果。"""
        executor = _make_executor({"m2510-C-3100": m2510_call})
        result = executor._calculate_generic_volume(
            weight=5,
            price=3100.0,
            account_assets=_account(),
            trade_rule={"sizing_mode": "lots"},
            symbol="m2510-C-3100",
        )
        assert result == 5.0


class TestSizingModePremiumWeight:
    """``sizing_mode='premium_weight'`` 与期货同公式（按权利金权重）。"""

    def test_premium_weight_formula(self, m2510_call: InstrumentField) -> None:
        executor = _make_executor({"m2510-C-3100": m2510_call})
        result = executor._calculate_generic_volume(
            weight=0.05,
            price=120.0,
            account_assets=_account(1_000_000.0),
            trade_rule={"sizing_mode": "premium_weight"},
            symbol="m2510-C-3100",
        )
        # 1_000_000 × 0.05 / (120 × 10) ≈ 41.66 → 截断到 41
        assert result == 41.0


class TestRoundLots:
    """取整规则：quantity_precision / 最小交易单位 / 默认整数。"""

    def test_quantity_precision_round(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.123,
            price=4000.0,
            account_assets=_account(1_000_000.0),
            trade_rule={"quantity_precision": 1},
            symbol="rb2510",
        )
        # 1_000_000 × 0.123 / 40000 = 3.075 → round(., 1) = 3.1
        assert result == 3.1

    def test_min_volume_floor(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.21,
            price=4000.0,
            account_assets=_account(1_000_000.0),
            trade_rule={"最小交易单位": 2},
            symbol="rb2510",
        )
        # 1_000_000 × 0.21 / 40000 = 5.25 → 最小单位=2 → floor(5.25/2)*2 = 4
        assert result == 4.0

    def test_default_integer_floor(self, rb_future: InstrumentField) -> None:
        executor = _make_executor({"rb2510": rb_future})
        result = executor._calculate_generic_volume(
            weight=0.21,
            price=4000.0,
            account_assets=_account(1_000_000.0),
            trade_rule={},
            symbol="rb2510",
        )
        # 1_000_000 × 0.21 / 40000 = 5.25 → 默认整数取整 = 5
        assert result == 5.0

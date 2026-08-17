"""``CtpTrader.calculate_required_margin`` 保证金计算测试.

聚焦点：

- 期货长 / 短保证金率分别取 ``LongMarginRatio`` / ``ShortMarginRatio``
- CTP 合约表保证金率为 0 时，从 ``trade_rule.margin_ratio`` 兜底
- 缺合约信息时返回 0 并日志告警
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from axile.executor.ctp.core.objects import InstrumentField

# CTP 协议常量：买 / 卖方向
THOST_FTDC_D_Buy = "0"
THOST_FTDC_D_Sell = "1"


def _make_trader_with_instruments(instruments: dict[str, InstrumentField]):
    """构造一个最小 trader 实例（不走 __init__），仅为测试 calculate_required_margin。"""
    from axile.executor.ctp.core.trader import CtpTrader

    trader = CtpTrader.__new__(CtpTrader)
    trader.instruments = instruments
    trader.logger = MagicMock()
    return trader


@pytest.fixture
def rb_future() -> InstrumentField:
    return InstrumentField(
        InstrumentID="rb2510",
        ProductClass="1",
        VolumeMultiple=10,
        LongMarginRatio=0.10,
        ShortMarginRatio=0.12,
    )


@pytest.fixture
def m_put_with_zero_short_ratio() -> InstrumentField:
    """模拟 CTP 合约表 ShortMarginRatio=0 的期权（典型踩坑场景）。"""
    return InstrumentField(
        InstrumentID="m2510-P-2900",
        ProductClass="2",
        OptionsType="2",
        VolumeMultiple=10,
        LongMarginRatio=0.05,
        ShortMarginRatio=0.0,
    )


class TestRequiredMargin:
    def test_future_long_uses_long_ratio(self, rb_future: InstrumentField) -> None:
        trader = _make_trader_with_instruments({"rb2510": rb_future})
        margin = trader.calculate_required_margin("rb2510", THOST_FTDC_D_Buy, 4000.0, 5)
        # 4000 × 5 × 10 × 0.10 = 20_000
        assert margin == 20_000.0

    def test_future_short_uses_short_ratio(self, rb_future: InstrumentField) -> None:
        trader = _make_trader_with_instruments({"rb2510": rb_future})
        margin = trader.calculate_required_margin("rb2510", THOST_FTDC_D_Sell, 4000.0, 5)
        # 4000 × 5 × 10 × 0.12 = 24_000
        assert margin == 24_000.0

    def test_zero_ratio_uses_trade_rule_fallback(self, m_put_with_zero_short_ratio: InstrumentField) -> None:
        """期权卖方在 CTP 合约表 ratio=0 时，应使用 trade_rule.margin_ratio 兜底。"""
        trader = _make_trader_with_instruments({"m2510-P-2900": m_put_with_zero_short_ratio})

        margin = trader.calculate_required_margin(
            "m2510-P-2900",
            THOST_FTDC_D_Sell,
            120.0,
            3,
            trade_rule={"margin_ratio": 0.18},
        )
        # 120 × 3 × 10 × 0.18 = 648
        assert margin == 648.0

    def test_zero_ratio_without_fallback_warns_and_returns_zero(
        self, m_put_with_zero_short_ratio: InstrumentField
    ) -> None:
        """既无 CTP 配置也无 trade_rule 兜底，必须告警并返回 0（暴露问题不放行无限杠杆）。"""
        trader = _make_trader_with_instruments({"m2510-P-2900": m_put_with_zero_short_ratio})

        margin = trader.calculate_required_margin("m2510-P-2900", THOST_FTDC_D_Sell, 120.0, 3)
        assert margin == 0.0
        # 应触发 warning 日志
        assert trader.logger.warning.called

    def test_trade_rule_does_not_override_valid_ctp_ratio(self, rb_future: InstrumentField) -> None:
        """CTP 合约表已有有效 ratio 时，trade_rule 不应覆盖（保留 CTP 数据为准）。"""
        trader = _make_trader_with_instruments({"rb2510": rb_future})

        margin = trader.calculate_required_margin(
            "rb2510",
            THOST_FTDC_D_Buy,
            4000.0,
            5,
            trade_rule={"margin_ratio": 0.50},  # 故意给一个错误高值
        )
        # 应仍取 CTP 的 0.10，得 20_000，不取 trade_rule 的 0.50
        assert margin == 20_000.0

    def test_missing_instrument_returns_zero(self) -> None:
        trader = _make_trader_with_instruments({})
        margin = trader.calculate_required_margin("unknown", THOST_FTDC_D_Buy, 4000.0, 5)
        assert margin == 0.0
        assert trader.logger.warning.called

    def test_invalid_trade_rule_value_ignored(self, m_put_with_zero_short_ratio: InstrumentField) -> None:
        """trade_rule.margin_ratio 类型错误（如字符串）应被忽略，回到告警 + 0 路径。"""
        trader = _make_trader_with_instruments({"m2510-P-2900": m_put_with_zero_short_ratio})

        margin = trader.calculate_required_margin(
            "m2510-P-2900",
            THOST_FTDC_D_Sell,
            120.0,
            3,
            trade_rule={"margin_ratio": "0.18"},  # 字符串，应被拒绝
        )
        assert margin == 0.0

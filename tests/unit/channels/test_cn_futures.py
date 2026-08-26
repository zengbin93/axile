"""国内期货合约身份与手数量化。"""

import pytest

from axile.channels.cn_futures import canonicalize_cn_futures_symbol, quantize_cn_futures_quantity


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("TA2701", "TA701"),
        ("TA701", "TA701"),
        ("CZCE.TA2701", "TA701"),
        ("CF2701", "CF701"),
        ("TA2701C5000", "TA701C5000"),
        ("TA701C5000", "TA701C5000"),
        ("SR2709P6200", "SR709P6200"),
        ("cu2606C69000", "cu2606C69000"),
        ("m2701-C-4000", "m2701-C-4000"),
        ("rb2610", "rb2610"),
        ("m2701", "m2701"),
        ("c2611", "c2611"),
        ("CF3701", "CF3701"),
    ],
)
def test_canonicalize_czce_four_digit_only(symbol: str, expected: str) -> None:
    """只压缩郑商所最近十年位的四位年期货/期权，DCE/SHFE 四位年不动。"""
    assert canonicalize_cn_futures_symbol(symbol, reference_year=2026) == expected


def test_quantize_truncates_toward_zero_like_executor() -> None:
    """与天勤 ``int(权益 × 权重 / (价格 × 乘数))`` 向零截断一致。"""
    equity = 992_670.6124999999
    assert quantize_cn_futures_quantity(0.13, equity, 30775.0) == 4.0
    assert quantize_cn_futures_quantity(0.03, equity, 22800.0) == 1.0
    assert quantize_cn_futures_quantity(-0.08, equity, 27500.0) == -2.0
    assert quantize_cn_futures_quantity(-0.06, equity, 32960.0) == -1.0


def test_quantize_invalid_notional_is_zero() -> None:
    assert quantize_cn_futures_quantity(0.13, 1000.0, 0.0) == 0.0

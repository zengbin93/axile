from __future__ import annotations

import pytest

from axile.common.gm_helpers import to_gm_symbol


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600000.SH", "SHSE.600000"),
        ("000001.SZ", "SZSE.000001"),
        ("920000.BJ", "BJSE.920000"),
        ("SHSE.600000", "SHSE.600000"),
    ],
)
def test_to_gm_symbol_converts_supported_tushare_codes(symbol: str, expected: str) -> None:
    assert to_gm_symbol(symbol) == expected


def test_to_gm_symbol_rejects_unknown_exchange_suffix() -> None:
    with pytest.raises(ValueError, match="格式或交易所不受支持"):
        to_gm_symbol("600000.HK")


def test_to_gm_symbol_rejects_malformed_symbol() -> None:
    with pytest.raises(ValueError, match="格式或交易所不受支持"):
        to_gm_symbol("600000SH")

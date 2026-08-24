from __future__ import annotations

import pytest

from axile.common.gm_symbols import GMSymbolResolver
from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_input import GMAccountConfig, UnifiedStandardInput


@pytest.fixture
def resolver() -> GMSymbolResolver:
    return GMSymbolResolver()


@pytest.mark.parametrize(
    ("axile_symbol", "gm_symbol"),
    [
        ("600000.SH", "SHSE.600000"),
        ("000001.SZ", "SZSE.000001"),
        ("920000.BJ", "BJSE.920000"),
    ],
)
def test_resolves_supported_symbols_in_both_directions(
    resolver: GMSymbolResolver,
    axile_symbol: str,
    gm_symbol: str,
) -> None:
    assert resolver.to_gm(axile_symbol) == gm_symbol
    assert resolver.to_gm(gm_symbol) == gm_symbol
    assert resolver.to_axile(gm_symbol) == axile_symbol
    assert resolver.to_axile(axile_symbol) == axile_symbol


@pytest.mark.parametrize("symbol", ["600000", "600000.HK", "SH.600000", "shse.600000", "ABC.SH"])
def test_rejects_malformed_or_unsupported_inputs(resolver: GMSymbolResolver, symbol: str) -> None:
    with pytest.raises(ValueError, match="格式或交易所不受支持"):
        resolver.to_gm(symbol)


def test_unknown_gm_output_is_preserved(resolver: GMSymbolResolver) -> None:
    assert resolver.to_axile("CFFEX.IF2609") == "CFFEX.IF2609"


def test_normalizes_all_standard_input_symbol_fields_without_mutating_source(
    resolver: GMSymbolResolver,
) -> None:
    standard_input = UnifiedStandardInput(
        channel_type=TradeChannel.GM,
        account_config=GMAccountConfig(
            connection_mode="terminal",
            account_id="account",
            token="token",
            terminal_path="C:/gm",
        ),
        curr_target={"SHSE.600000": 0.2},
        last_target={"000001.SZ": 0.1},
        symbol_algorithms={"BJSE.920000": {"method": "SINGLE-MAKER", "params": {}}},
        trade_rules={"SHSE.600000": {"min_notional": 100}},
        forbidden_symbols=["SHSE.600000", "600000.SH"],
        risk_symbols=["SZSE.000001"],
    )

    normalized = resolver.normalize_input(standard_input)

    assert normalized.curr_target == {"600000.SH": 0.2}
    assert normalized.last_target == {"000001.SZ": 0.1}
    assert list(normalized.symbol_algorithms) == ["920000.BJ"]
    assert normalized.trade_rules == {"600000.SH": {"min_notional": 100}}
    assert normalized.forbidden_symbols == ["600000.SH"]
    assert normalized.risk_symbols == ["000001.SZ"]
    assert standard_input.curr_target == {"SHSE.600000": 0.2}


def test_rejects_conflicting_alias_values(resolver: GMSymbolResolver) -> None:
    standard_input = UnifiedStandardInput(
        channel_type=TradeChannel.GM,
        account_config=GMAccountConfig(
            connection_mode="terminal",
            account_id="account",
            token="token",
            terminal_path="C:/gm",
        ),
        curr_target={"600000.SH": 0.1, "SHSE.600000": 0.2},
    )

    with pytest.raises(ValueError, match="配置不一致"):
        resolver.normalize_input(standard_input)

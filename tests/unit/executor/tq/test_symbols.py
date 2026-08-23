from __future__ import annotations

import pytest

from axile.executor.tq.symbols import TQInstrument, TQSymbolResolver


def _resolver() -> TQSymbolResolver:
    return TQSymbolResolver(
        [
            TQInstrument("SHFE.rb2610", "rb2610", "SHFE", "FUTURE"),
            TQInstrument("DCE.m2609-C-2700", "m2609-C-2700", "DCE", "OPTION"),
            TQInstrument("KQ.m@SHFE.rb", "m@SHFE.rb", "KQ", "CONT"),
            TQInstrument("SSE.600000", "600000", "SSE", "STOCK"),
        ]
    )


def test_resolves_derivative_symbols_in_both_directions() -> None:
    resolver = _resolver()

    assert resolver.to_tq("rb2610", for_trade=True) == "SHFE.rb2610"
    assert resolver.to_axile("SHFE.rb2610") == "rb2610"
    assert resolver.to_tq("m2609-C-2700", for_trade=True) == "DCE.m2609-C-2700"


def test_quote_only_symbol_is_preserved_but_rejected_for_trade() -> None:
    resolver = _resolver()

    assert resolver.to_tq("KQ.m@SHFE.rb") == "KQ.m@SHFE.rb"
    assert resolver.to_tq("SSE.600000") == "SSE.600000"
    assert resolver.to_axile("SSE.600000") == "SSE.600000"
    with pytest.raises(ValueError, match="仅支持行情查询"):
        resolver.to_tq("SSE.600000", for_trade=True)


def test_expired_derivative_is_queryable_but_not_tradable() -> None:
    resolver = TQSymbolResolver([TQInstrument("SHFE.rb2501", "rb2501", "SHFE", "FUTURE", expired=True)])

    assert resolver.to_tq("rb2501") == "SHFE.rb2501"
    with pytest.raises(ValueError, match="仅支持行情查询"):
        resolver.to_tq("rb2501", for_trade=True)


def test_unknown_and_ambiguous_symbols_fail_explicitly() -> None:
    resolver = TQSymbolResolver(
        [
            TQInstrument("SHFE.x2601", "x2601", "SHFE", "FUTURE"),
            TQInstrument("DCE.x2601", "x2601", "DCE", "FUTURE"),
        ]
    )

    with pytest.raises(ValueError, match="不存在"):
        resolver.to_tq("missing")
    with pytest.raises(ValueError, match="多个天勤代码"):
        resolver.to_tq("x2601")

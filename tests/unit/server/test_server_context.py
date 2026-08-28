"""自定义组合函数统一账户上下文测试."""

from __future__ import annotations

from typing import cast

import pytest

from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData
from axile.server.context import Context, PortfolioExecutor, build_sample_context


def _quote(symbol: str) -> UnifiedPriceData:
    return UnifiedPriceData(
        symbol=symbol,
        last_price=123.0,
        bid_price=122.0,
        ask_price=124.0,
        bid_volume=1.0,
        ask_volume=1.0,
        volume=10.0,
        timestamp=1,
        update_time="2026-08-28T10:00:00",
    )


class _Executor:
    def __init__(self) -> None:
        self.assets_calls = 0
        self.market_calls: list[list[str]] = []
        self.pending_symbols: list[str | None] = []
        self.trade_queries: list[tuple[str, str]] = []
        self.assets = UnifiedAccountAssets(
            available_cash=100.0,
            total_asset=300.0,
            market_value=200.0,
            positions=[
                Position(symbol="SHFE.rb2610", volume=2, available_volume=2, market_value=100, direction="多头"),
                Position(symbol="SHFE.rb2610", volume=1, available_volume=1, market_value=50, direction="空头"),
                Position(symbol="SHFE.ag2612", volume=1, available_volume=1, market_value=50, direction="多头"),
            ],
        )

    def get_account_assets(self) -> UnifiedAccountAssets:
        self.assets_calls += 1
        return self.assets

    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        self.market_calls.append(symbols)
        return {"SHFE.rb2610": _quote("SHFE.rb2610")}

    def get_pending_orders(self, symbol: str | None = None) -> list[UnifiedOrder]:
        self.pending_symbols.append(symbol)
        return cast("list[UnifiedOrder]", ["pending"])

    def query_trades(self, symbol: str, order_id: str) -> list[TradeRecord]:
        self.trade_queries.append((symbol, order_id))
        return cast("list[TradeRecord]", ["trade"])


@pytest.fixture
def executor() -> _Executor:
    return _Executor()


@pytest.fixture
def context(executor: _Executor) -> Context:
    return Context(cast("PortfolioExecutor", executor))


def test_account_and_positions_share_lazy_snapshot(context: Context, executor: _Executor) -> None:
    assert context.account.total_asset == 300.0
    assert len(context.positions) == 3
    assert executor.assets_calls == 1


def test_get_positions_preserves_simultaneous_long_and_short(context: Context) -> None:
    positions = context.get_positions("SHFE.rb2610")
    assert [position.direction for position in positions] == ["多头", "空头"]
    assert context.get_positions(direction=PositionDirection.SHORT) == [positions[1]]
    assert context.get_positions(direction="多头") == [positions[0], context.positions[2]]


def test_quote_accepts_normalized_symbol_and_caches_aliases(context: Context, executor: _Executor) -> None:
    quote = context.get_quote("rb2610")
    assert quote.symbol == "SHFE.rb2610"
    assert context.get_price("rb2610") == 123.0
    assert context.get_quote("SHFE.rb2610") is quote
    assert executor.market_calls == [["rb2610"]]


def test_order_queries_delegate_to_executor(context: Context, executor: _Executor) -> None:
    assert context.get_pending_orders("SHFE.rb2610") == ["pending"]
    assert context.query_trades("SHFE.rb2610", "order-1") == ["trade"]
    assert executor.pending_symbols == ["SHFE.rb2610"]
    assert executor.trade_queries == [("SHFE.rb2610", "order-1")]


def test_sample_context_supports_account_and_arbitrary_price() -> None:
    context = build_sample_context()
    assert context.account.total_asset == 1_000_000.0
    assert context.get_price("ANY.SYMBOL") == 100.0


def test_legacy_summary_fields_are_not_available(context: Context) -> None:
    with pytest.raises(AttributeError):
        _ = context.today_return

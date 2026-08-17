"""``data_converter.get_account_assets`` 持仓 extras 字段单测.

聚焦点:

- 组合拆腿持仓的 ``extra.combination_origin`` 透传
- 期权合约的 ``extra.instrument_kind`` / ``option_type`` 等元数据
- 期货合约只标 ``instrument_kind='future'``，不写期权字段
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from axile.executor.ctp.core.objects import InstrumentField, TradingAccountField
from axile.executor.ctp.utils import data_converter as dc


@pytest.fixture
def stub_md_client() -> MagicMock:
    """构造 md_client 桩件，订阅成功 + 返回 LastPrice。"""
    md = MagicMock()
    md.subscribe = MagicMock()

    quote = MagicMock()
    quote.LastPrice = 4000.0
    md.get_quote = MagicMock(return_value=quote)
    return md


def _account() -> TradingAccountField:
    return TradingAccountField(
        AccountID="user01",
        BrokerID="9999",
        Available=200_000.0,
        Balance=300_000.0,
        Commission=0.0,
        CloseProfit=0.0,
        PositionProfit=0.0,
        FrozenMargin=0.0,
        FrozenCash=0.0,
        CurrMargin=0.0,
        Deposit=0.0,
        Withdraw=0.0,
        TradingDay="20260502",
        CurrencyID="CNY",
    )


def _summary_entry(symbol: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instrument_id": symbol,
        "exchange_id": "DCE",
        "long_position": 5,
        "short_position": 0,
        "net_position": 5,
        "long_yd_position": 0,
        "short_yd_position": 0,
        "today_position": 5,
        "SettlementPrice": 4000.0,
    }
    base.update(overrides)
    return base


def _make_trader_stub(
    instruments: dict[str, InstrumentField],
    summary: list[dict[str, Any]],
) -> MagicMock:
    trader = MagicMock()
    trader.query_account.return_value = _account()
    trader.query_positions.return_value = {sym: object() for sym in instruments}
    trader.get_positions_summary.return_value = summary
    trader.instruments = instruments
    return trader


class TestPositionExtras:
    """覆盖持仓 extras 字段的写入路径。"""

    def test_future_position_marks_instrument_kind(
        self, stub_md_client: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # data_converter 内部 sleep 1s，把它跳过免得拖慢测试。
        monkeypatch.setattr(dc.time, "sleep", lambda _s: None)
        rb = InstrumentField(InstrumentID="rb2510", ProductClass="1", VolumeMultiple=10)
        trader = _make_trader_stub({"rb2510": rb}, [_summary_entry("rb2510")])

        result = dc.get_account_assets(trader, stub_md_client)

        positions = result["positions"]
        assert len(positions) == 1
        extra = positions[0]["extra"]
        assert extra["instrument_kind"] == "future"
        assert "option_type" not in extra
        assert "combination_origin" not in extra

    def test_option_position_carries_option_metadata(
        self, stub_md_client: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(dc.time, "sleep", lambda _s: None)
        m_call = InstrumentField(
            InstrumentID="m2510-C-3100",
            ProductClass="2",
            OptionsType="1",
            StrikePrice=3100.0,
            UnderlyingInstrID="m2510",
            UnderlyingMultiple=10.0,
            ExpireDate="20251015",
            VolumeMultiple=10,
        )
        trader = _make_trader_stub(
            {"m2510-C-3100": m_call},
            [_summary_entry("m2510-C-3100")],
        )

        result = dc.get_account_assets(trader, stub_md_client)

        extra = result["positions"][0]["extra"]
        assert extra["instrument_kind"] == "option"
        assert extra["option_type"] == "call"
        assert extra["strike_price"] == 3100.0
        assert extra["underlying"] == "m2510"
        assert extra["expire_date"] == "20251015"

    def test_split_leg_position_carries_combination_origin(
        self,
        stub_md_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(dc.time, "sleep", lambda _s: None)
        a_leg = InstrumentField(InstrumentID="a2605", ProductClass="1", VolumeMultiple=10)
        trader = _make_trader_stub(
            {"a2605": a_leg},
            [_summary_entry("a2605", combination_origin="SPC a2605&m2605")],
        )

        result = dc.get_account_assets(trader, stub_md_client)

        extra = result["positions"][0]["extra"]
        assert extra["combination_origin"] == "SPC a2605&m2605"
        assert extra["instrument_kind"] == "future"

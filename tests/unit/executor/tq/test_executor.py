from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import TQAccountConfig
from axile.executor.models.unified_order import OrderDirection, OrderType
from axile.executor.tq import TQExecutor
from axile.executor.tq.tq_execute import TQTradingTimeCheck, TQTradingTimeStatus


class FakeApi:
    def __init__(self) -> None:
        self.quote = {
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "last_price": 3200,
            "bid_price1": 3199,
            "ask_price1": 3201,
            "bid_volume1": 2,
            "ask_volume1": 3,
            "price_tick": 1,
            "volume_multiple": 10,
            "datetime": 1_700_000_000_000_000_000,
        }
        self.order = {
            "order_id": "o1",
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "direction": "BUY",
            "offset": "OPEN",
            "price_type": "LIMIT",
            "volume_orign": 2,
            "volume_left": 2,
            "limit_price": 3200,
            "status": "ALIVE",
        }
        self.trade = {
            "trade_id": "t1",
            "order_id": "o1",
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "direction": "BUY",
            "offset": "OPEN",
            "trade_volume": 1,
            "trade_price": 3200,
            "trade_date_time": 1_700_000_000_000_000_000,
        }
        self.insert_args: dict[str, object] = {}
        self.order_lookups: list[str] = []
        self.canceled: list[str] = []
        self.closed = False

    def query_quotes(self, *, ins_class: str, expired: bool = False) -> list[str]:
        return ["SHFE.rb2610"] if ins_class == "FUTURE" and not expired else []

    def wait_update(self, *, deadline: float) -> bool:
        del deadline
        return False

    def is_changing(self, _entity: object) -> bool:
        return False

    def get_quote(self, _symbol: str) -> dict[str, object]:
        return self.quote

    def get_trading_calendar(self, start: date, end: date) -> object:
        rows = []
        current = start
        while current <= end:
            rows.append({"date": current, "trading": current.weekday() < 5})
            current += timedelta(days=1)
        return SimpleNamespace(to_dict=lambda _orient: rows)

    def get_account(self) -> dict[str, object]:
        return {"available": 900_000, "balance": 1_000_000}

    def get_position(self) -> dict[str, object]:
        return {
            "SHFE.rb2610": SimpleNamespace(
                pos_long_today=1,
                pos_long_his=2,
                pos_short_today=0,
                pos_short_his=0,
                volume_long_frozen=0,
                position_cost_long=30_000,
                open_price_long=3000,
            )
        }

    def insert_order(self, **kwargs: object) -> dict[str, object]:
        self.insert_args = kwargs
        self.order = {
            **self.order,
            "order_id": kwargs["order_id"],
            "direction": kwargs["direction"],
            "offset": kwargs["offset"],
            "volume_orign": kwargs["volume"],
            "volume_left": kwargs["volume"],
            "limit_price": kwargs["limit_price"] or 0,
        }
        return self.order

    def cancel_order(self, order_id: str) -> None:
        self.canceled.append(order_id)

    def get_order(self, order_id: str | None = None) -> dict[str, object]:
        if order_id is not None:
            self.order_lookups.append(order_id)
        return self.order if order_id else {"o1": self.order}

    def get_trade(self) -> dict[str, object]:
        return {"t1": self.trade}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def executor(monkeypatch: pytest.MonkeyPatch) -> tuple[TQExecutor, FakeApi]:
    api = FakeApi()
    monkeypatch.setattr(TQExecutor, "_build_api", staticmethod(lambda _config: api))
    instance = TQExecutor(TQAccountConfig(account_mode="kq", tq_username="user", tq_password="secret"))
    try:
        yield instance, api
    finally:
        instance.close()


def test_executor_converts_queries_and_order_primitives(
    executor: tuple[TQExecutor, FakeApi], monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, api = executor
    monkeypatch.setattr(
        instance,
        "_check_tq_symbol_trading_time",
        lambda _api, _sessions, _now: TQTradingTimeCheck(TQTradingTimeStatus.OPEN),
    )

    market = instance.get_market_data(["rb2610"])
    assets = instance.get_account_assets()
    order = instance._place_order_impl(
        "rb2610",
        OrderDirection.SELL,
        OrderType.LIMIT,
        2,
        3199,
        offset_flag="3",
    )

    assert market["rb2610"].last_price == 3200
    assert assets.positions[0].symbol == "rb2610"
    assert assets.positions[0].extra["long_yd"] == 2
    assert order.symbol == "rb2610"
    assert {key: value for key, value in api.insert_args.items() if key != "order_id"} == {
        "symbol": "SHFE.rb2610",
        "direction": "SELL",
        "offset": "CLOSETODAY",
        "volume": 2,
        "limit_price": 3199.0,
    }
    native_order_id = api.insert_args["order_id"]
    assert isinstance(native_order_id, str) and len(native_order_id) == 32
    assert order.order_id == native_order_id
    assert api.order_lookups == []
    assert instance._cancel_order_impl("rb2610", "o1") is True
    assert api.canceled == ["o1"]
    assert instance._query_trades_impl("rb2610", "o1")[0].symbol == "rb2610"


def test_executor_uses_contract_multiplier_and_rejects_fractional_lots(
    executor: tuple[TQExecutor, FakeApi],
) -> None:
    instance, _api = executor
    assets = UnifiedAccountAssets(available_cash=1_000_000, total_asset=1_000_000, market_value=0, positions=[])

    assert instance.get_tick_size("rb2610") == 1
    assert instance._calculate_generic_volume(0.32, 3200, assets, {}, symbol="rb2610") == 10
    with pytest.raises(ValueError, match="正整数手"):
        instance._place_order_impl("rb2610", OrderDirection.BUY, OrderType.LIMIT, 1.5, 3200)

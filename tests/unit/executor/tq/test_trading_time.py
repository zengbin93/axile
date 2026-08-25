from __future__ import annotations

from datetime import date, datetime
from threading import get_ident
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from axile.executor.models.unified_input import TQAccountConfig
from axile.executor.models.unified_order import OrderDirection, OrderType
from axile.executor.tq import TQExecutor
from axile.executor.tq.tq_execute import TQTradingTimeStatus

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Calendar:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.rows


class FakeApi:
    def __init__(self) -> None:
        self.owner: int | None = None
        self.insert_calls = 0
        self.calendar_error: Exception | None = None
        self.quotes = {
            "SHFE.rb2610": SimpleNamespace(
                trading_time={
                    "day": [["09:00:00", "10:15:00"], ["10:30:00", "11:30:00"], ["13:30:00", "15:00:00"]],
                    "night": [["21:00:00", "25:00:00"]],
                }
            ),
            "SHFE.ag2612": SimpleNamespace(
                trading_time={"day": [["09:00:00", "15:00:00"]], "night": [["21:00:00", "25:00:00"]]}
            ),
            "SHFE.au2612": SimpleNamespace(
                trading_time={"day": [["09:00:00", "15:00:00"]], "night": [["21:00:00", "26:30:00"]]}
            ),
            "SHFE.bu2612": SimpleNamespace(trading_time={"day": [["09:00:00", "15:00:00"]], "night": []}),
        }
        self.calendar_rows: list[dict[str, object]] = []

    def query_quotes(self, *, ins_class: str | None = None, expired: bool = False) -> list[str]:
        if expired:
            return []
        if ins_class in {None, "FUTURE"}:
            return list(self.quotes)
        return []

    def wait_update(self, *, deadline: float) -> bool:
        del deadline
        return False

    def is_changing(self, _entity: object) -> bool:
        return False

    def get_quote(self, symbol: str) -> object:
        self.owner = get_ident()
        return self.quotes[symbol]

    def get_trading_calendar(self, _start: date, _end: date) -> _Calendar:
        self.owner = get_ident()
        if self.calendar_error:
            raise self.calendar_error
        return _Calendar(self.calendar_rows)

    def insert_order(self, **_kwargs: object) -> dict[str, object]:
        self.owner = get_ident()
        self.insert_calls += 1
        return {
            "order_id": "order-1",
            "exchange_id": "SHFE",
            "instrument_id": "rb2610",
            "direction": "BUY",
            "offset": "OPEN",
            "price_type": "LIMIT",
            "volume_orign": 1,
            "volume_left": 1,
            "limit_price": 3200,
            "status": "ALIVE",
        }

    def close(self) -> None:
        pass


@pytest.fixture
def executor(monkeypatch: pytest.MonkeyPatch) -> tuple[TQExecutor, FakeApi]:
    api = FakeApi()
    monkeypatch.setattr(TQExecutor, "_build_api", staticmethod(lambda _config: api))
    instance = TQExecutor(TQAccountConfig(account_mode="kq", tq_username="user", tq_password="secret"))
    try:
        yield instance, api
    finally:
        instance.close()


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=_SHANGHAI)


def _set_calendar(api: FakeApi, *trading_dates: str) -> None:
    api.calendar_rows = [
        {"date": value, "trading": value in trading_dates}
        for value in ("2026-08-21", "2026-08-22", "2026-08-24", "2026-08-25")
    ]


@pytest.mark.parametrize(
    ("symbol", "moment", "expected"),
    [
        ("rb2610", "2026-08-24T09:30:00", TQTradingTimeStatus.OPEN),
        ("rb2610", "2026-08-24T10:15:00", TQTradingTimeStatus.CLOSED),
        ("rb2610", "2026-08-24T11:45:00", TQTradingTimeStatus.CLOSED),
        ("rb2610", "2026-08-24T21:00:00", TQTradingTimeStatus.OPEN),
        ("rb2610", "2026-08-25T01:00:00", TQTradingTimeStatus.CLOSED),
        ("bu2612", "2026-08-24T21:30:00", TQTradingTimeStatus.CLOSED),
        ("ag2612", "2026-08-25T00:59:59", TQTradingTimeStatus.OPEN),
        ("ag2612", "2026-08-25T01:00:00", TQTradingTimeStatus.CLOSED),
        ("au2612", "2026-08-25T02:29:59", TQTradingTimeStatus.OPEN),
        ("au2612", "2026-08-25T02:30:00", TQTradingTimeStatus.CLOSED),
    ],
)
def test_symbol_trading_time_respects_product_sessions(
    executor: tuple[TQExecutor, FakeApi], symbol: str, moment: str, expected: TQTradingTimeStatus
) -> None:
    instance, api = executor
    _set_calendar(api, "2026-08-21", "2026-08-24", "2026-08-25")

    assert instance._check_symbol_trading_time(symbol, _at(moment)).status is expected
    assert api.owner == instance._require_runtime()._thread.ident


def test_night_session_requires_its_next_trading_day(executor: tuple[TQExecutor, FakeApi]) -> None:
    instance, api = executor
    _set_calendar(api, "2026-08-21")

    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-21T21:30:00")).status is TQTradingTimeStatus.CLOSED
    _set_calendar(api, "2026-08-21", "2026-08-22")
    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-22T00:30:00")).status is TQTradingTimeStatus.OPEN


def test_unavailable_quote_and_calendar_fail_closed(executor: tuple[TQExecutor, FakeApi]) -> None:
    instance, api = executor
    _set_calendar(api, "2026-08-24")
    api.quotes["SHFE.rb2610"].trading_time = None
    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-24T09:30:00")).status is (
        TQTradingTimeStatus.QUOTE_TRADING_TIME_UNAVAILABLE
    )

    api.quotes["SHFE.rb2610"].trading_time = {"day": [["09:00:00", "15:00:00"]], "night": []}
    api.calendar_error = RuntimeError("calendar unavailable")
    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-24T09:30:00")).status is (
        TQTradingTimeStatus.CALENDAR_UNAVAILABLE
    )

    api.calendar_error = None
    api.calendar_rows = [{"date": "2026-08-25", "trading": True}]
    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-24T09:30:00")).status is (
        TQTradingTimeStatus.CALENDAR_UNAVAILABLE
    )


def test_place_order_rechecks_current_symbol_before_submitting(executor: tuple[TQExecutor, FakeApi]) -> None:
    instance, api = executor
    _set_calendar(api, "2026-08-24")
    api.quotes["SHFE.rb2610"].trading_time = {"day": [], "night": []}

    with pytest.raises(Exception, match="CLOSED"):
        instance._place_order_impl("rb2610", OrderDirection.BUY, OrderType.LIMIT, 1, 3200)

    assert api.insert_calls == 0


def test_place_order_checks_and_submits_in_one_runtime_command(
    executor: tuple[TQExecutor, FakeApi], monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, api = executor
    api.quotes["SHFE.rb2610"].trading_time = {"day": [["00:00:00", "24:00:00"]], "night": []}
    api.get_trading_calendar = lambda start, _end: _Calendar([{"date": start, "trading": True}])
    runtime = instance._require_runtime()
    call = runtime.call
    calls = 0

    def counted_call(operation: object, *, timeout: float | None = None) -> object:
        nonlocal calls
        calls += 1
        return call(operation, timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "call", counted_call)
    instance._place_order_impl("rb2610", OrderDirection.BUY, OrderType.LIMIT, 1, 3200)

    assert calls == 1
    assert api.insert_calls == 1

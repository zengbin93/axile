from __future__ import annotations

from datetime import date, datetime, timedelta
from threading import get_ident
from zoneinfo import ZoneInfo

import pytest

from axile.executor.models.unified_input import TQAccountConfig
from axile.executor.models.unified_order import OrderDirection, OrderType
from axile.executor.tq import TQExecutor
from axile.executor.tq.tq_execute import TQTradingTimeCheck, TQTradingTimeStatus

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Calendar:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.rows


class FakeApi:
    futures = [
        "SHFE.rb2610",
        "SHFE.ag2612",
        "SHFE.au2612",
        "SHFE.bu2612",
        "SHFE.xx2601",
        "INE.sc2609",
        "DCE.a2609",
        "CZCE.TA609",
        "GFEX.si2609",
        "CFFEX.IF2609",
        "CFFEX.T2609",
    ]
    options = ["SHFE.rb2610C3200"]
    combines = ["SHFE.rb2610&rb2611"]

    def __init__(self) -> None:
        self.owner: int | None = None
        self.insert_calls = 0
        self.calendar_error: Exception | None = None
        self.calendar_rows: list[dict[str, object]] | None = None
        self.closed_dates: set[date] = set()

    def query_quotes(self, *, ins_class: str | None = None, expired: bool = False) -> list[str]:
        if expired:
            return []
        return {
            "FUTURE": self.futures,
            "OPTION": self.options,
            "COMBINE": self.combines,
        }.get(ins_class, self.futures + self.options + self.combines)

    def wait_update(self, *, deadline: float) -> bool:
        del deadline
        return False

    def is_changing(self, _entity: object) -> bool:
        return False

    def get_trading_calendar(self, start: date, end: date) -> _Calendar:
        self.owner = get_ident()
        if self.calendar_error:
            raise self.calendar_error
        if self.calendar_rows is not None:
            return _Calendar(self.calendar_rows)
        rows = []
        current = start
        while current <= end:
            rows.append({"date": current, "trading": current.weekday() < 5 and current not in self.closed_dates})
            current += timedelta(days=1)
        return _Calendar(rows)

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


@pytest.mark.parametrize(
    ("symbol", "moment", "expected"),
    [
        ("rb2610", "2026-08-24T09:30:00", TQTradingTimeStatus.OPEN),
        ("rb2610", "2026-08-24T10:15:00", TQTradingTimeStatus.CLOSED),
        ("rb2610", "2026-08-24T11:45:00", TQTradingTimeStatus.CLOSED),
        ("rb2610", "2026-08-21T21:00:00", TQTradingTimeStatus.OPEN),
        ("rb2610", "2026-08-21T23:00:00", TQTradingTimeStatus.CLOSED),
        ("bu2612", "2026-08-21T22:59:59", TQTradingTimeStatus.OPEN),
        ("bu2612", "2026-08-21T23:00:00", TQTradingTimeStatus.CLOSED),
        ("ag2612", "2026-08-22T02:29:59", TQTradingTimeStatus.OPEN),
        ("ag2612", "2026-08-22T02:30:00", TQTradingTimeStatus.CLOSED),
        ("au2612", "2026-08-22T02:29:59", TQTradingTimeStatus.OPEN),
        ("au2612", "2026-08-22T02:30:00", TQTradingTimeStatus.CLOSED),
    ],
)
def test_symbol_trading_time_respects_product_sessions(
    executor: tuple[TQExecutor, FakeApi], symbol: str, moment: str, expected: TQTradingTimeStatus
) -> None:
    instance, api = executor

    assert instance._check_symbol_trading_time(symbol, _at(moment)).status is expected
    if expected is TQTradingTimeStatus.OPEN:
        assert api.owner == instance._require_runtime()._thread.ident


@pytest.mark.parametrize(
    ("symbol", "moment"),
    [
        ("sc2609", "2026-08-22T02:29:59"),
        ("a2609", "2026-08-21T22:59:59"),
        ("TA609", "2026-08-21T22:59:59"),
        ("si2609", "2026-08-24T09:30:00"),
        ("IF2609", "2026-08-24T09:30:00"),
        ("T2609", "2026-08-24T15:14:59"),
    ],
)
def test_static_sessions_cover_each_exchange(executor: tuple[TQExecutor, FakeApi], symbol: str, moment: str) -> None:
    instance, _ = executor

    assert instance._check_symbol_trading_time(symbol, _at(moment)).status is TQTradingTimeStatus.OPEN


def test_friday_night_continues_to_saturday_but_sunday_night_is_closed(executor: tuple[TQExecutor, FakeApi]) -> None:
    instance, _ = executor

    assert instance._check_symbol_trading_time("ag2612", _at("2026-08-21T21:30:00")).status is TQTradingTimeStatus.OPEN
    assert instance._check_symbol_trading_time("ag2612", _at("2026-08-22T00:30:00")).status is TQTradingTimeStatus.OPEN
    assert (
        instance._check_symbol_trading_time("ag2612", _at("2026-08-23T21:30:00")).status is TQTradingTimeStatus.CLOSED
    )
    assert (
        instance._check_symbol_trading_time("ag2612", _at("2026-08-24T00:30:00")).status is TQTradingTimeStatus.CLOSED
    )


def test_night_session_before_holiday_is_closed(executor: tuple[TQExecutor, FakeApi]) -> None:
    instance, api = executor
    api.closed_dates.add(date(2026, 8, 21))

    assert (
        instance._check_symbol_trading_time("rb2610", _at("2026-08-20T21:30:00")).status is TQTradingTimeStatus.CLOSED
    )


@pytest.mark.parametrize("symbol", ["xx2601", "rb2610C3200", "rb2610&rb2611", "missing2601"])
def test_uncovered_option_and_combine_fail_closed(executor: tuple[TQExecutor, FakeApi], symbol: str) -> None:
    instance, _ = executor

    assert instance._check_symbol_trading_time(symbol, _at("2026-08-24T09:30:00")).status is (
        TQTradingTimeStatus.QUOTE_TRADING_TIME_UNAVAILABLE
    )


def test_calendar_failure_or_missing_date_fail_closed(executor: tuple[TQExecutor, FakeApi]) -> None:
    instance, api = executor
    api.calendar_error = RuntimeError("calendar unavailable")
    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-24T09:30:00")).status is (
        TQTradingTimeStatus.CALENDAR_UNAVAILABLE
    )

    api.calendar_error = None
    api.calendar_rows = [{"date": "2026-08-25", "trading": True}]
    assert instance._check_symbol_trading_time("rb2610", _at("2026-08-24T09:30:00")).status is (
        TQTradingTimeStatus.CALENDAR_UNAVAILABLE
    )


def test_place_order_rechecks_current_symbol_before_submitting(
    executor: tuple[TQExecutor, FakeApi], monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, api = executor
    monkeypatch.setattr(
        instance,
        "_check_tq_symbol_trading_time",
        lambda _api, _sessions, _now: TQTradingTimeCheck(TQTradingTimeStatus.CLOSED),
    )

    with pytest.raises(Exception, match="CLOSED"):
        instance._place_order_impl("rb2610", OrderDirection.BUY, OrderType.LIMIT, 1, 3200)

    assert api.insert_calls == 0


def test_place_order_checks_and_submits_in_one_runtime_command(
    executor: tuple[TQExecutor, FakeApi], monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, api = executor
    runtime = instance._require_runtime()
    call = runtime.call
    calls = 0

    def counted_call(operation: object, *, timeout: float | None = None) -> object:
        nonlocal calls
        calls += 1
        return call(operation, timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "call", counted_call)
    monkeypatch.setattr(
        instance,
        "_check_tq_symbol_trading_time",
        lambda _api, _sessions, _now: TQTradingTimeCheck(TQTradingTimeStatus.OPEN),
    )
    instance._place_order_impl("rb2610", OrderDirection.BUY, OrderType.LIMIT, 1, 3200)

    assert calls == 1
    assert api.insert_calls == 1

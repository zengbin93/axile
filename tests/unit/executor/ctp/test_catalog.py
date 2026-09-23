"""目录隔离与流式等待测试，不连接柜台。"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.ctp.ctp_execute import CTPExecutor, _PendingQuery
from axile.executor.ctp_catalog import CatalogStore, LocalCatalogProvider, decode_catalog
from axile.executor.ctp_query_wait import QueryIdleClock

KEY = ("9999", "tcp://unused:1", "20260914")
ROWS = {"ag2612": {"InstrumentID": "ag2612", "PriceTick": 1.0}}


def test_local_catalog_single_load_and_immutable_consumers():
    provider = LocalCatalogProvider(CatalogStore())
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return ROWS

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(provider.get, KEY, loader)
        assert entered.wait(2)
        second = pool.submit(provider.get, KEY, loader)
        release.set()
        a, b = first.result(2), second.result(2)
    assert calls == [1]
    assert a["ag2612"].PriceTick == b["ag2612"].PriceTick == 1.0
    with pytest.raises(TypeError):
        a["other"] = a["ag2612"]
    with pytest.raises(FrozenInstanceError):
        a["ag2612"].PriceTick = 2.0
    with pytest.raises(TypeError):
        a["ag2612"].values["PriceTick"] = 2.0


@pytest.mark.parametrize(
    "key",
    [
        ("other", KEY[1], KEY[2]),
        (KEY[0], "tcp://different:1", KEY[2]),
        (KEY[0], KEY[1], "20260915"),
    ],
)
def test_catalog_source_and_day_are_isolated(key):
    provider = LocalCatalogProvider(CatalogStore())
    provider.get(KEY, lambda: ROWS)
    expected = {"rb2610": {"InstrumentID": "rb2610"}}
    assert list(provider.get(key, lambda: expected)) == ["rb2610"]


def test_failed_generation_never_publishes_or_poison_retries():
    store = CatalogStore()
    old = store.acquire(KEY, "one")
    assert store.acquire(KEY, "two") is old
    store.release_owner("one")
    replacement = store.acquire(KEY, "two")
    assert replacement is not old
    with pytest.raises(RuntimeError, match="失效"):
        store.publish(KEY, old, ROWS)
    assert store.inspect(old)[1] == "CTP 合约目录加载者已退出"
    with pytest.raises(ValueError, match="空结果"):
        store.publish(KEY, replacement, {})
    assert store.inspect(replacement)[0] is None
    store.publish(KEY, replacement, ROWS)
    assert decode_catalog(store.inspect(replacement)[0])["ag2612"].PriceTick == 1.0


def test_idle_timeout_excludes_copy_time_and_accepts_long_stream():
    now = [0.0]
    idle = QueryIdleClock(lambda: now[0])
    done = threading.Event()
    now[0] = 100  # 模拟发送前限流等待。
    idle.sent()
    for _ in range(10):
        now[0] += 14
        assert not idle.timed_out(15, done)
        assert idle.enter()
        now[0] += 100  # 本地复制再慢也不是网络空闲。
        assert not idle.timed_out(15, done)
        idle.leave()
    assert idle.processing_seconds == 1000
    assert idle.max_idle == 14
    now[0] += 15
    assert idle.timed_out(15, done)
    assert not idle.enter()


def test_first_callback_timeout_and_completed_last_callback():
    now = [0.0]
    done = threading.Event()
    idle = QueryIdleClock(lambda: now[0])
    now[0] = 15
    assert idle.timed_out(15, done)
    idle = QueryIdleClock(lambda: now[0])
    assert idle.enter()
    done.set()
    idle.leave()
    now[0] += 100
    assert not idle.timed_out(15, done)


def test_late_last_callback_cannot_win_against_timeout():
    now = [0.0]
    idle = QueryIdleClock(lambda: now[0])
    now[0] = 16
    assert not idle.enter(15)
    assert idle.timed_out(15, threading.Event())


def test_cancelled_local_waiter_does_not_abort_other_accounts():
    store = CatalogStore()
    load = store.acquire(KEY, "loading")
    provider = LocalCatalogProvider(store)

    def cancel():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        provider.get(KEY, lambda: pytest.fail("must not load"), cancel)
    store.publish(KEY, load, ROWS)
    assert provider.get(KEY, lambda: pytest.fail("must hit"))["ag2612"].PriceTick == 1


def test_record_progress_is_throttled_and_ready_executor_stops_reporting(monkeypatch):
    now = [10.0]
    monkeypatch.setattr("axile.executor.ctp.ctp_execute.time.monotonic", lambda: now[0])
    executor = CTPExecutor(TradeChannel.CTP)
    phases = []
    executor.set_catalog_provider(SimpleNamespace(progress=phases.append))
    for _ in range(20):
        executor._catalog_progress("对账记录", throttled=True)
        now[0] += 0.25
    assert len(phases) == 5
    executor._ready = True
    now[0] += 60
    executor._catalog_progress("对账记录", throttled=True)
    assert len(phases) == 5


def test_copy_exception_finishes_query_and_ignores_late_success(monkeypatch):
    executor = CTPExecutor(TradeChannel.CTP)
    pending = _PendingQuery([], threading.Event(), idle=QueryIdleClock())
    executor._pending_queries[7] = pending

    def broken(_row):
        raise ValueError("copy failed")

    monkeypatch.setattr("axile.executor.ctp.ctp_execute._copy_native_row", broken)
    executor._query_response(SimpleNamespace(InstrumentID="ag2612"), None, 7, False)
    assert pending.done.is_set()
    assert str(pending.error) == "copy failed"
    assert pending.idle.processing == 0
    executor._query_response(None, None, 7, True)
    assert str(pending.error) == "copy failed"

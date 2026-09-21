"""用真实 spawn 进程和独立管道验证合约目录服务。"""

import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from axile.executor.ctp_catalog import CatalogStore
from axile.server.execution.worker_backend import worker as worker_entry
from axile.server.execution.worker_backend import worker_state
from axile.server.execution.worker_backend.catalog import CatalogSession, RemoteCatalogProvider
from axile.server.execution.worker_backend.manager import WorkerBackendManager, WorkerBackendTimeoutError
from axile.server.execution.worker_backend.protocol import (
    WorkerBackendErrorPayload,
    WorkerBackendRequest,
    WorkerBackendResponse,
)

pytestmark = pytest.mark.slow

KEY = ("9999", "tcp://unused:1", "20260914")
ROWS = {"ag2612": {"InstrumentID": "ag2612", "PriceTick": 1.0}}


@pytest.mark.parametrize("failure", [TimeoutError("wait"), BrokenPipeError("send"), EOFError("recv")])
def test_failed_rpc_discards_channel_and_never_consumes_late_response(failure):
    connection = Mock()
    connection.poll.return_value = True
    if isinstance(failure, TimeoutError):
        connection.poll.return_value = False
    elif isinstance(failure, BrokenPipeError):
        connection.send.side_effect = failure
    else:
        connection.recv.side_effect = failure
    provider = RemoteCatalogProvider(connection)
    with pytest.raises(type(failure)):
        provider._rpc("acquire", key=KEY)
    assert provider.failed
    connection.close.assert_called_once()
    sends, receives = connection.send.call_count, connection.recv.call_count
    # 即使迟到响应已经到达，失效管道也不能再被 fail/end 消费。
    connection.poll.return_value = True
    connection.recv.side_effect = None
    connection.recv.return_value = {"token": "late", "owner": True}
    for op in ("fail", "end", "begin"):
        with pytest.raises(RuntimeError, match="已失效"):
            provider._rpc(op)
    assert connection.send.call_count == sends
    assert connection.recv.call_count == receives


@pytest.mark.parametrize("release_fails", [False, True])
def test_audit_failure_still_releases_connection_and_preserves_initialization_error(monkeypatch, release_fails):
    original = BrokenPipeError("end failed")
    provider = Mock()
    provider.end.side_effect = original
    close = Mock(side_effect=RuntimeError("native close failed") if release_fails else None)
    executor = SimpleNamespace(_verify_connection=lambda: False, set_catalog_provider=Mock(), close=close)
    state = worker_state._WorkerBackendState(executor=executor, catalog_provider=provider)
    monkeypatch.setattr(worker_state, "_resolve_executor", lambda *args, **kwargs: executor)
    monkeypatch.setattr(worker_state, "_prepare_executor", Mock())
    monkeypatch.setattr(worker_state, "initialize_executor_instance", Mock())
    monkeypatch.setattr(worker_state, "_finalize_executor", Mock(side_effect=RuntimeError("audit flush failed")))
    with pytest.raises(BrokenPipeError) as caught:
        worker_state._resolve_prepared_executor(state=state, account=Mock(), execution_id="test", audit_context={})
    assert caught.value is original
    close.assert_called_once()
    assert state.requires_worker_restart
    assert state.executor is None


def test_close_without_original_error_reports_audit_failure_after_releasing(monkeypatch):
    original = RuntimeError("audit flush failed")
    executor = SimpleNamespace(close=Mock())
    monkeypatch.setattr(worker_state, "_finalize_executor", Mock(side_effect=original))
    with pytest.raises(RuntimeError) as caught:
        worker_state._close_executor(executor)
    assert caught.value is original
    executor.close.assert_called_once()


@pytest.mark.parametrize("reason", ["catalog", "cleanup"])
def test_worker_loop_reports_restart_separately_and_exits(monkeypatch, reason):
    request = WorkerBackendRequest("request", "prepare", {}, None, {})
    original = WorkerBackendErrorPayload("timeout_error", "original query timeout")
    connection = Mock()
    connection.recv.side_effect = [request, AssertionError("must not accept another request")]
    control = Mock()
    control.recv.side_effect = EOFError()
    catalog_connection = Mock()
    catalog = SimpleNamespace(failed=reason == "catalog", request_id="")
    monkeypatch.setattr(worker_entry, "RemoteCatalogProvider", lambda _: catalog)

    def handle(req, state):
        state.requires_worker_restart = reason == "cleanup"
        return WorkerBackendResponse(req.request_id, "error", error=original)

    monkeypatch.setattr(worker_entry, "_handle_worker_request", handle)
    worker_entry.run_worker_backend_loop(connection, 1, control, catalog_connection)
    connection.send.assert_called_once()
    response = connection.send.call_args.args[0]
    assert response.error is original
    assert response.requires_worker_restart
    assert connection.recv.call_count == 1


def test_session_connection_close_is_serialized():
    entered = threading.Event()
    release = threading.Event()
    connection = Mock(closed=False)

    def close():
        entered.set()
        assert release.wait(3)
        connection.closed = True

    connection.close.side_effect = close
    session = CatalogSession(connection, CatalogStore())
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(session._close_connection)
        assert entered.wait(3)
        second = pool.submit(session._close_connection)
        release.set()
        first.result(3)
        second.result(3)
    connection.close.assert_called_once()


@pytest.mark.parametrize("fail_broken,end_broken", [(False, True), (True, False), (True, True)])
def test_failed_initialization_preserves_original_error(monkeypatch, fail_broken, end_broken):
    original = TimeoutError("original instrument timeout")
    provider = RemoteCatalogProvider(Mock())

    def rpc(op, **payload):
        if op == "acquire":
            return {"token": "test", "owner": True}
        if op == "poll":
            return {"data": None, "error": None}
        if (op == "fail" and fail_broken) or (op == "end" and end_broken):
            raise BrokenPipeError(op)
        return {}

    monkeypatch.setattr(provider, "_rpc", rpc)

    def loader():
        raise original

    executor = Mock()
    executor._verify_connection.return_value = False
    state = worker_state._WorkerBackendState(executor=executor, account_id=1, catalog_provider=provider)
    monkeypatch.setattr(worker_state, "_resolve_executor", lambda *args, **kwargs: executor)
    monkeypatch.setattr(worker_state, "_prepare_executor", Mock())
    monkeypatch.setattr(worker_state, "initialize_executor_instance", lambda _: provider.get(KEY, loader))
    close = Mock()
    monkeypatch.setattr(worker_state, "_close_executor", close)
    with pytest.raises(TimeoutError) as caught:
        worker_state._resolve_prepared_executor(state=state, account=Mock(), execution_id="test", audit_context={})
    assert caught.value is original
    close.assert_called_once_with(executor)
    assert state.executor is None
    assert state.account_id is None


def test_successful_initialization_with_failed_end_discards_executor(monkeypatch):
    provider = Mock()
    original = BrokenPipeError("end failed")
    provider.end.side_effect = original
    executor = Mock()
    executor._verify_connection.return_value = False
    state = worker_state._WorkerBackendState(executor=executor, catalog_provider=provider)
    monkeypatch.setattr(worker_state, "_resolve_executor", lambda *args, **kwargs: executor)
    monkeypatch.setattr(worker_state, "_prepare_executor", Mock())
    initialize = Mock()
    close = Mock()
    monkeypatch.setattr(worker_state, "initialize_executor_instance", initialize)
    monkeypatch.setattr(worker_state, "_close_executor", close)
    with pytest.raises(BrokenPipeError) as caught:
        worker_state._resolve_prepared_executor(state=state, account=Mock(), execution_id="test", audit_context={})
    assert caught.value is original
    initialize.assert_called_once_with(executor)
    provider.end.assert_called_once()
    close.assert_called_once_with(executor)
    assert state.executor is None


def _catalog_child(pipe, results, gate, counter):
    provider = RemoteCatalogProvider(pipe)
    provider.request_id = "test"
    provider.begin()

    def loader():
        with counter.get_lock():
            counter.value += 1
        assert gate.wait(10)
        return {**ROWS, **{f"contract{i}": {"InstrumentID": f"contract{i}", "PriceTick": 0.2} for i in range(28_241)}}

    try:
        catalog = provider.get(KEY, loader)
        # 同一 worker 重连必须命中，不能因 owner 相同重复加载。
        second = provider.get(KEY, loader)
        results.put((catalog["ag2612"].PriceTick, second["ag2612"].PriceTick))
    finally:
        provider.end()
        pipe.close()


def test_spawn_accounts_share_one_native_query():
    ctx = multiprocessing.get_context("spawn")
    both_acquired = threading.Event()

    class TrackingStore(CatalogStore):
        def __init__(self):
            super().__init__()
            self.owners = set()
            self.tracking_lock = threading.Lock()

        def acquire(self, key, owner):
            load = super().acquire(key, owner)
            with self.tracking_lock:
                self.owners.add(owner)
                if len(self.owners) == 2:
                    both_acquired.set()
            return load

    store = TrackingStore()
    gate = ctx.Event()
    counter = ctx.Value("i", 0)
    results = ctx.Queue()
    sessions, processes = [], []
    try:
        for _ in range(2):
            parent, child = ctx.Pipe()
            session = CatalogSession(parent, store)
            session.thread.start()
            process = ctx.Process(target=_catalog_child, args=(child, results, gate, counter))
            process.start()
            child.close()
            sessions.append(session)
            processes.append(process)
        assert both_acquired.wait(15)
        gate.set()
        assert results.get(timeout=20) == (1.0, 1.0)
        assert results.get(timeout=20) == (1.0, 1.0)
        assert counter.value == 1
        for process in processes:
            process.join(5)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        for session in sessions:
            session.close()
        results.close()
        results.join_thread()


def _crashing_loader(pipe):
    RemoteCatalogProvider(pipe)._rpc("acquire", key=KEY)
    os._exit(1)


def test_spawn_loader_crash_releases_generation():
    ctx = multiprocessing.get_context("spawn")
    store = CatalogStore()
    parent, child = ctx.Pipe()
    session = CatalogSession(parent, store)
    session.thread.start()
    process = ctx.Process(target=_crashing_loader, args=(child,))
    process.start()
    child.close()
    try:
        process.join(15)
        assert process.exitcode == 1
        session.thread.join(3)
        assert not session.thread.is_alive()
        replacement = store.acquire(KEY, "new-worker")
        assert replacement.owner == "new-worker"
        store.publish(KEY, replacement, ROWS)
        assert store.inspect(replacement)[0] is not None
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        session.close()


def test_loader_disconnect_wakes_waiter_and_next_request_can_retry():
    ctx = multiprocessing.get_context("spawn")
    store = CatalogStore()
    parent, child = ctx.Pipe()
    session = CatalogSession(parent, store)
    session.thread.start()
    provider = RemoteCatalogProvider(child)
    acquired = provider._rpc("acquire", key=KEY)
    load = store.acquire(KEY, "waiting")
    assert load.token == acquired["token"]
    child.close()
    session.thread.join(2)
    assert not session.thread.is_alive()
    assert store.inspect(load)[1] == "CTP 合约目录加载者已退出"
    assert store.acquire(KEY, "replacement") is not load
    session.close()


def test_initialization_progress_extends_only_current_request():
    parent, child = multiprocessing.Pipe()
    session = CatalogSession(parent, CatalogStore())
    handle = SimpleNamespace(catalog=session)
    request = SimpleNamespace(request_id="current")
    try:
        session.request_id = "current"
        session.active = True
        session.started = 5
        session.updated = 100
        remaining = WorkerBackendManager._remaining_response_time(handle, request, 30, 120)
        assert remaining == 40
        with pytest.raises(WorkerBackendTimeoutError, match="无进展"):
            WorkerBackendManager._remaining_response_time(handle, request, 30, 160)
        session.active = False
        session.finished = 125
        assert WorkerBackendManager._remaining_response_time(handle, request, 30, 130) == 20
        request.request_id = "next"
        assert WorkerBackendManager._remaining_response_time(handle, request, 150, 130) == 20
    finally:
        parent.close()
        child.close()


def test_catalog_polling_alone_never_refreshes_watchdog(monkeypatch):
    now = [10.0]
    monkeypatch.setattr("axile.server.execution.worker_backend.catalog.time.monotonic", lambda: now[0])
    parent, child = multiprocessing.Pipe()
    store = CatalogStore()
    store.acquire(KEY, "loader")
    session = CatalogSession(parent, store)
    try:
        session._dispatch({"op": "begin", "request_id": "waiting"})
        acquired = session._dispatch({"op": "acquire", "key": KEY})
        now[0] = 100
        for _ in range(5):
            session._dispatch({"op": "poll", "token": acquired["token"]})
        assert session.snapshot("waiting")[1] == 10
    finally:
        parent.close()
        child.close()


def test_waiter_progress_tracks_loader_not_polling():
    parent, child = multiprocessing.Pipe()
    store = CatalogStore()
    session = CatalogSession(parent, store)
    session.thread.start()
    provider = RemoteCatalogProvider(child)
    provider.request_id = "waiter"
    provider.begin()
    load = store.acquire(KEY, "loader")
    acquired = threading.Event()
    outcomes = []

    def checkpoint():
        acquired.set()

    def wait():
        outcomes.append(provider.get(KEY, lambda: pytest.fail("重复加载"), checkpoint))

    thread = threading.Thread(target=wait)
    thread.start()
    try:
        assert acquired.wait(2)
        store.advance(load)
        store.publish(KEY, load, ROWS)
        thread.join(3)
        assert not thread.is_alive()
        assert outcomes[0]["ag2612"].PriceTick == 1.0
    finally:
        store.fail(load, "test ended")
        child.close()
        session.close()

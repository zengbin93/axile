from __future__ import annotations

import threading
import time

import pytest

from axile.executor.tq.runtime import TQRuntime


class FakeApi:
    def __init__(self) -> None:
        self.owner = threading.get_ident()
        self.query_count = 0
        self.wait_count = 0
        self.closed = False

    def query_quotes(self, *, ins_class: str | None = None, expired: bool = False) -> list[str]:
        self.query_count += 1
        if expired:
            return []
        if ins_class == "FUTURE":
            return ["SHFE.rb2610"]
        if ins_class is None:
            return ["SHFE.rb2610", "KQ.m@SHFE.rb", "SSWE.AU9999"]
        return []

    def wait_update(self, *, deadline: float) -> bool:
        del deadline
        self.wait_count += 1
        return False

    def is_changing(self, _entity: object) -> bool:
        return False

    def get_order(self) -> dict[str, object]:
        return {}

    def get_trade(self) -> dict[str, object]:
        return {}

    def close(self) -> None:
        self.closed = True


def test_runtime_owns_api_and_builds_catalog_once() -> None:
    api: FakeApi | None = None

    def factory() -> FakeApi:
        nonlocal api
        api = FakeApi()
        return api

    runtime = TQRuntime(factory)
    try:
        owner = runtime.call(lambda _api: threading.get_ident())
        assert api is not None
        assert owner == api.owner
        assert owner != threading.get_ident()
        assert runtime.resolver.to_tq("rb2610") == "SHFE.rb2610"
        assert runtime.resolver.to_tq("KQ.m@SHFE.rb") == "KQ.m@SHFE.rb"
        with pytest.raises(ValueError, match="仅支持行情查询"):
            runtime.resolver.to_tq("KQ.m@SHFE.rb", for_trade=True)
        assert api.query_count == 8
        assert api.wait_count >= 1
    finally:
        runtime.close()

    assert api is not None and api.closed is True


def test_pending_command_timeout_cancels_before_execution() -> None:
    runtime = TQRuntime(FakeApi)
    started = threading.Event()
    release = threading.Event()
    first_errors: list[BaseException] = []

    def block_owner(_api: object) -> None:
        started.set()
        release.wait(1)

    def run_first() -> None:
        try:
            runtime.call(block_owner)
        except BaseException as exc:  # noqa: BLE001 - 线程断言需要带回主线程
            first_errors.append(exc)

    worker = threading.Thread(target=run_first)
    worker.start()
    try:
        assert started.wait(1)
        executed = threading.Event()
        with pytest.raises(TimeoutError, match="命令排队超时"):
            runtime.call(lambda _api: executed.set(), timeout=0.01)
        release.set()
        worker.join(1)
        runtime.call(lambda _api: None)
        assert not worker.is_alive()
        assert first_errors == []
        assert not executed.is_set()
    finally:
        release.set()
        worker.join(1)
        runtime.close()


def test_running_mutation_waits_for_one_determinate_result() -> None:
    runtime = TQRuntime(FakeApi)
    started = threading.Event()
    release = threading.Event()
    calls = 0
    results: list[str] = []
    errors: list[BaseException] = []

    def mutation(_api: object) -> str:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(1)
        return "order-1"

    def invoke() -> None:
        try:
            results.append(runtime.call(mutation, timeout=0.01))
        except BaseException as exc:  # noqa: BLE001 - 线程断言需要带回主线程
            errors.append(exc)

    worker = threading.Thread(target=invoke)
    worker.start()
    try:
        assert started.wait(1)
        time.sleep(0.03)
        assert worker.is_alive()
        release.set()
        worker.join(1)
        assert not worker.is_alive()
        assert errors == []
        assert results == ["order-1"]
        assert calls == 1
    finally:
        release.set()
        worker.join(1)
        runtime.close()


def test_operation_result_does_not_wait_for_next_update() -> None:
    class BlockingPumpApi(FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.block_pump = False
            self.release_pump = threading.Event()

        def wait_update(self, *, deadline: float) -> bool:
            super().wait_update(deadline=deadline)
            if self.block_pump:
                self.release_pump.wait(1)
            return False

    api = BlockingPumpApi()
    runtime = TQRuntime(lambda: api, command_timeout=0.05)
    try:

        def operation(_api: object) -> str:
            api.block_pump = True
            return "done"

        assert runtime.call(operation) == "done"
    finally:
        api.release_pump.set()
        runtime.close()


def test_runtime_propagates_operation_error() -> None:
    runtime = TQRuntime(FakeApi)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            runtime.call(lambda _api: (_ for _ in ()).throw(ValueError("boom")))
    finally:
        runtime.close()


def test_runtime_emits_quote_snapshots() -> None:
    class ChangingApi(FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.quote = {"instrument_id": "rb2610", "exchange_id": "SHFE", "last_price": 3200}
            self.changed = False

        def get_quote(self, _symbol: str) -> dict[str, object]:
            return self.quote

        def is_changing(self, entity: object) -> bool:
            return self.changed and entity is self.quote

    api = ChangingApi()
    runtime = TQRuntime(lambda: api)
    events: list[tuple[str, dict[str, object]]] = []
    runtime.add_listener(lambda kind, row: events.append((kind, row)))
    try:
        runtime.subscribe(["SHFE.rb2610"])
        runtime.call(lambda _api: setattr(api, "changed", True))
        assert events[-1] == (
            "quote",
            {"instrument_id": "rb2610", "exchange_id": "SHFE", "last_price": 3200},
        )
        api.quote["last_price"] = 3300
        assert events[-1][1]["last_price"] == 3200
    finally:
        runtime.close()


def test_runtime_propagates_wait_update_and_close_errors() -> None:
    class BrokenPumpApi(FakeApi):
        fail = False

        def wait_update(self, *, deadline: float) -> bool:
            del deadline
            if self.fail:
                raise OSError("pump failed")
            return False

    runtime = TQRuntime(BrokenPumpApi)
    assert runtime.call(lambda api: setattr(api, "fail", True)) is None
    deadline = time.monotonic() + 1
    while runtime.is_alive() and time.monotonic() < deadline:
        time.sleep(0.001)
    with pytest.raises(RuntimeError, match="异常停止"):
        runtime.call(lambda _api: None)
    runtime.close()

    class BrokenCloseApi(FakeApi):
        def close(self) -> None:
            raise OSError("close failed")

    runtime = TQRuntime(BrokenCloseApi)
    # Ensure the event pump has entered its steady state before closing it.
    deadline = time.monotonic() + 1
    while runtime.call(lambda api: getattr(api, "wait_count")) < 1 and time.monotonic() < deadline:
        pass
    with pytest.raises(RuntimeError, match="close failed"):
        runtime.close()

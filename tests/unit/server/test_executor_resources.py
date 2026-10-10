"""一次性执行器最终关闭、取消及失败清理回归。"""

import asyncio
from types import SimpleNamespace

import pytest

from axile.server import account_assets
from axile.server.execution import lifecycle
from axile.server.execution.resources import close_executor


@pytest.mark.parametrize("failure", [None, "flush", "clear", "close"])
def test_cleanup_always_closes_after_flushing_and_clearing(monkeypatch, failure):
    calls = []

    def action(name):
        calls.append(name)
        if name == failure:
            raise RuntimeError(name)

    async def flush(executor):
        action("flush")

    executor = SimpleNamespace(clear_execution_runtime=lambda: action("clear"), stop=lambda: action("close"))
    monkeypatch.setattr(lifecycle, "flush_account_control_records", flush)
    asyncio.run(lifecycle.cleanup_executor_runtime(executor))
    assert calls == ["flush", "clear", "close"]


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_final_cleanup_preserves_original_execution_outcome(monkeypatch, outcome):
    original = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("execution failed")
    released = []

    def stop():
        released.append(True)
        raise RuntimeError("cleanup failed")

    async def flush(executor):
        raise RuntimeError("flush failed")

    monkeypatch.setattr(lifecycle, "flush_account_control_records", flush)
    executor = SimpleNamespace(stop=stop)

    async def run():
        try:
            if outcome != "success":
                raise original
            return "result"
        finally:
            await lifecycle.cleanup_executor_runtime(executor)

    if outcome == "success":
        assert asyncio.run(run()) == "result"
    else:
        with pytest.raises(type(original)) as caught:
            asyncio.run(run())
        assert caught.value is original
    assert released == [True]


@pytest.mark.parametrize("stage", ["guard", "initialize", "runtime", "cancel"])
def test_prepare_failure_releases_executor_without_masking_cause(monkeypatch, stage):
    original = asyncio.CancelledError() if stage == "cancel" else RuntimeError(stage)
    calls = []

    def fail():
        raise original

    async def guard(*args):
        if stage == "guard":
            fail()
        return None

    async def flush(executor):
        calls.append("flush")

    def close():
        calls.append("close")
        raise RuntimeError("close failed")

    executor = SimpleNamespace(
        set_audit_context=lambda value: None,
        set_audit_sink=lambda value: None,
        set_account_control_guard=lambda value: None,
        stop=close,
        _requires_connection_initialization=True,
        prepare_execution_runtime=fail if stage in {"runtime", "cancel"} else lambda: None,
        clear_execution_runtime=lambda: calls.append("clear"),
    )
    monkeypatch.setattr(lifecycle, "create_executor_instance", lambda account, initialize: executor)
    monkeypatch.setattr(lifecycle, "get_channel", lambda channel: SimpleNamespace(requires_pre_connect_guard=True))
    monkeypatch.setattr(
        lifecycle, "initialize_executor_instance", lambda executor: fail() if stage == "initialize" else None
    )
    monkeypatch.setattr(lifecycle, "build_server_execution_audit_sink", lambda: None)
    monkeypatch.setattr(lifecycle, "build_account_control_guard", guard)
    monkeypatch.setattr(lifecycle, "flush_account_control_records", flush)
    with pytest.raises(type(original)) as caught:
        asyncio.run(
            lifecycle.prepare_executor_runtime(
                SimpleNamespace(trade_channel="demo"), execution_id=None, audit_context={}
            )
        )
    assert caught.value is original
    assert calls == ["flush", "clear", "close"]


@pytest.mark.parametrize("failure", [False, True])
def test_asset_query_releases_transport_and_preserves_result_or_error(monkeypatch, failure):
    calls = []
    original = RuntimeError("asset query failed")

    def query():
        if failure:
            raise original
        return "assets"

    def stop():
        calls.append("close")
        raise RuntimeError("close failed")

    executor = SimpleNamespace(get_account_assets=query, stop=stop)
    monkeypatch.setattr(account_assets, "create_executor_instance", lambda account: executor)
    if failure:
        with pytest.raises(RuntimeError) as caught:
            account_assets._query_inline_account_assets(SimpleNamespace())
        assert caught.value is original
    else:
        assert account_assets._query_inline_account_assets(SimpleNamespace()) == "assets"
    assert calls == ["close"]


def test_close_falls_back_to_close_when_stop_is_unavailable():
    closed = []
    close_executor(SimpleNamespace(close=lambda: closed.append(True)))
    assert closed == [True]

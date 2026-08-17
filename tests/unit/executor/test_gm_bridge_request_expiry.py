"""GM bridge 请求超时失效测试。

覆盖 issue #28：调用方超时后请求必须失效，不能在 GM runtime 恢复后被延迟执行，
否则下单/撤单类请求会造成重复下单或错误撤单。
"""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from typing import Any

import pytest

from axile.executor.gm.core.api_bridge import GMSubscribeSymbolsRequest
from axile.executor.gm.core.bridge_context import (
    clear_gm_strategy_runtime_context,
    install_gm_strategy_runtime_context,
)
from axile.executor.gm.core.strategy_bridge import GMBridgeRequest, GMStrategyBridge


class _RecordingSink:
    """记录事件的最小 GMBridgeEventSink 实现。"""

    def dispatch_order_update(self, order: Any) -> None:
        """记录订单更新事件。"""

    def dispatch_trade_record(self, trade: Any) -> None:
        """记录成交事件。"""

    def dispatch_price_data(self, price_data: Any) -> None:
        """记录行情事件。"""

    def dispatch_runtime_log(self, event: Any) -> None:
        """记录 runtime 日志事件。"""


def _make_request(deadline: float | None = None) -> GMBridgeRequest:
    return GMBridgeRequest(
        request=GMSubscribeSymbolsRequest(symbols=["SHSE.600000"]),
        future=Future(),
        deadline=deadline,
    )


@pytest.fixture
def bridge_context() -> Any:
    """安装 GM 运行时上下文，测试结束后清理。"""
    request_queue: queue.Queue[GMBridgeRequest] = queue.Queue()
    install_gm_strategy_runtime_context(
        dispatcher=_RecordingSink(),
        ready_event=threading.Event(),
        stop_event=threading.Event(),
        stats={"order_status_received": 0, "execution_report_received": 0, "tick_received": 0, "errors": 0},
        subscribe_symbols=[],
        request_queue=request_queue,
        startup_state={"phase": "running"},
        runtime_stop_requested=threading.Event(),
        runtime_stop_lock=threading.Lock(),
    )
    yield request_queue
    clear_gm_strategy_runtime_context()


def test_submit_request_cancels_future_on_timeout() -> None:
    """调用方超时后必须取消 Future，使消费端守卫真正生效。"""
    bridge = GMStrategyBridge(
        token="token",
        account_id="acct",
        callback_dispatcher=_RecordingSink(),
    )
    bridge._running = True  # 绕过 start()，只验证提交路径

    with pytest.raises(TimeoutError):
        bridge._submit_request(GMSubscribeSymbolsRequest(symbols=["SHSE.600000"]), timeout=0.01)

    submitted = bridge._request_queue.get_nowait()
    assert submitted.future.cancelled(), "超时后 Future 必须被取消，否则消费端会延迟执行该请求"
    assert submitted.deadline is not None, "带 timeout 的请求必须带 deadline"


def test_submit_request_sets_no_deadline_without_timeout() -> None:
    """timeout=None 表示无限等待，不应设置 deadline。"""
    bridge = GMStrategyBridge(
        token="token",
        account_id="acct",
        callback_dispatcher=_RecordingSink(),
    )
    bridge._running = True

    thread = threading.Thread(
        target=lambda: bridge._submit_request(GMSubscribeSymbolsRequest(symbols=["SHSE.600000"]), timeout=None),
        daemon=True,
    )
    thread.start()

    deadline = time.monotonic() + 2.0
    submitted: GMBridgeRequest | None = None
    while time.monotonic() < deadline:
        try:
            submitted = bridge._request_queue.get_nowait()
            break
        except queue.Empty:
            time.sleep(0.01)

    assert submitted is not None, "请求未在预期时间内入队"
    assert submitted.deadline is None
    assert not submitted.is_expired()

    # 回填结果让后台线程退出，避免测试残留悬挂线程。
    if submitted.future.set_running_or_notify_cancel():
        submitted.future.set_result(None)
    thread.join(timeout=2.0)


def test_is_expired_respects_deadline() -> None:
    """deadline 到期后 is_expired 必须为真，未设置时恒为假。"""
    assert _make_request(deadline=None).is_expired() is False
    assert _make_request(deadline=time.monotonic() - 0.01).is_expired() is True
    assert _make_request(deadline=time.monotonic() + 60.0).is_expired() is False


def test_cancelled_request_is_not_dispatched(bridge_context: queue.Queue[GMBridgeRequest], monkeypatch: Any) -> None:
    """已取消的请求不得下发到 GM SDK。"""
    import axile.executor.gm.core.gm_strategy as gm_strategy

    dispatched: list[Any] = []
    monkeypatch.setattr(gm_strategy, "_dispatch_bridge_request", lambda req: dispatched.append(req))
    monkeypatch.setattr(gm_strategy, "_is_stopped", lambda: False)

    request = _make_request(deadline=time.monotonic() + 60.0)
    request.future.cancel()
    bridge_context.put(request)

    gm_strategy._process_bridge_requests(None)

    assert dispatched == [], "已取消的请求被下发到 SDK，存在重复下单风险"


def test_expired_request_is_not_dispatched(bridge_context: queue.Queue[GMBridgeRequest], monkeypatch: Any) -> None:
    """越过 deadline 的请求不得下发到 SDK，且以 TimeoutError 失败化。

    覆盖「调用方刚超时、消费端已把请求取出队列」这段取消标志覆盖不到的窗口。
    """
    import axile.executor.gm.core.gm_strategy as gm_strategy

    dispatched: list[Any] = []
    monkeypatch.setattr(gm_strategy, "_dispatch_bridge_request", lambda req: dispatched.append(req))
    monkeypatch.setattr(gm_strategy, "_is_stopped", lambda: False)

    request = _make_request(deadline=time.monotonic() - 0.01)
    bridge_context.put(request)

    gm_strategy._process_bridge_requests(None)

    assert dispatched == [], "过期请求被下发到 SDK，存在延迟下单/错误撤单风险"
    assert request.future.done()
    with pytest.raises(TimeoutError):
        request.future.result(timeout=0)


def test_live_request_is_dispatched(bridge_context: queue.Queue[GMBridgeRequest], monkeypatch: Any) -> None:
    """未过期、未取消的请求必须正常执行并回填结果。"""
    import axile.executor.gm.core.gm_strategy as gm_strategy

    dispatched: list[Any] = []

    def _fake_dispatch(req: Any) -> str:
        dispatched.append(req)
        return "ok"

    monkeypatch.setattr(gm_strategy, "_dispatch_bridge_request", _fake_dispatch)
    monkeypatch.setattr(gm_strategy, "_is_stopped", lambda: False)

    request = _make_request(deadline=time.monotonic() + 60.0)
    bridge_context.put(request)

    gm_strategy._process_bridge_requests(None)

    assert len(dispatched) == 1
    assert request.future.result(timeout=0) == "ok"


def test_dispatch_error_is_propagated(bridge_context: queue.Queue[GMBridgeRequest], monkeypatch: Any) -> None:
    """SDK 调用异常必须回填到 Future，不得吞掉。"""
    import axile.executor.gm.core.gm_strategy as gm_strategy

    def _boom(_req: Any) -> None:
        raise RuntimeError("sdk boom")

    monkeypatch.setattr(gm_strategy, "_dispatch_bridge_request", _boom)
    monkeypatch.setattr(gm_strategy, "_is_stopped", lambda: False)

    request = _make_request(deadline=time.monotonic() + 60.0)
    bridge_context.put(request)

    gm_strategy._process_bridge_requests(None)

    with pytest.raises(RuntimeError, match="sdk boom"):
        request.future.result(timeout=0)


def test_timeout_then_runtime_recovery_does_not_execute() -> None:
    """端到端：调用方超时后 GM runtime 恢复，该请求不得被执行。

    这是 issue #28 的核心验收场景——重复下单风险的直接回归。
    """
    import axile.executor.gm.core.gm_strategy as gm_strategy

    bridge = GMStrategyBridge(
        token="token",
        account_id="acct",
        callback_dispatcher=_RecordingSink(),
    )
    bridge._running = True

    # 1. 调用方提交请求并超时（模拟 GM runtime 卡死期间）
    with pytest.raises(TimeoutError):
        bridge._submit_request(GMSubscribeSymbolsRequest(symbols=["SHSE.600000"]), timeout=0.01)

    # 2. GM runtime 恢复，消费端开始处理积压队列
    install_gm_strategy_runtime_context(
        dispatcher=_RecordingSink(),
        ready_event=threading.Event(),
        stop_event=threading.Event(),
        stats={"order_status_received": 0, "execution_report_received": 0, "tick_received": 0, "errors": 0},
        subscribe_symbols=[],
        request_queue=bridge._request_queue,
        startup_state={"phase": "running"},
        runtime_stop_requested=threading.Event(),
        runtime_stop_lock=threading.Lock(),
    )
    try:
        dispatched: list[Any] = []
        original_dispatch = gm_strategy._dispatch_bridge_request
        gm_strategy._dispatch_bridge_request = lambda req: dispatched.append(req)  # type: ignore[assignment]
        original_is_stopped = gm_strategy._is_stopped
        gm_strategy._is_stopped = lambda: False  # type: ignore[assignment]
        try:
            gm_strategy._process_bridge_requests(None)
        finally:
            gm_strategy._dispatch_bridge_request = original_dispatch  # type: ignore[assignment]
            gm_strategy._is_stopped = original_is_stopped  # type: ignore[assignment]

        assert dispatched == [], "超时请求在 runtime 恢复后仍被执行——重复下单风险未修复"
    finally:
        clear_gm_strategy_runtime_context()


def test_fail_pending_requests_tolerates_concurrent_cancel() -> None:
    """stop() 回填与调用方超时取消并发时不得抛 InvalidStateError。"""
    bridge = GMStrategyBridge(
        token="token",
        account_id="acct",
        callback_dispatcher=_RecordingSink(),
    )

    cancelled = _make_request(deadline=time.monotonic() + 60.0)
    cancelled.future.cancel()
    pending = _make_request(deadline=time.monotonic() + 60.0)

    bridge._request_queue.put(cancelled)
    bridge._request_queue.put(pending)

    bridge._fail_pending_requests(RuntimeError("GM bridge 已停止"))

    assert cancelled.future.cancelled()
    with pytest.raises(RuntimeError, match="GM bridge 已停止"):
        pending.future.result(timeout=0)

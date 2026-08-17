"""worker backend manager 的单元测试。"""

from __future__ import annotations

import asyncio
from threading import Lock

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.models.execution_result import ExecutionStatus
from axile.server.execution.worker_backend.manager import (
    WorkerBackendManager,
    WorkerBackendTimeoutError,
)
from axile.server.execution.worker_backend.protocol import (
    WorkerBackendErrorPayload,
    WorkerBackendRequest,
    WorkerBackendResponse,
)
from tests.unit.server._execution_test_support import build_account


class _FakeProcess:
    def __init__(self, *, is_alive: bool = True, join_stops: bool = True) -> None:
        self._is_alive = is_alive
        self._join_stops = join_stops
        self.join_calls: list[float] = []
        self.terminate_called = False
        self.kill_called = False

    def is_alive(self) -> bool:
        return self._is_alive

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(0.0 if timeout is None else timeout)
        if self._join_stops:
            self._is_alive = False

    def terminate(self) -> None:
        self.terminate_called = True
        self._is_alive = False

    def kill(self) -> None:
        self.kill_called = True
        self._is_alive = False


class _FakeConnection:
    def __init__(self, *, poll_result: bool = True) -> None:
        self.closed = False
        self.sent_commands: list[str] = []
        self.last_request_id = ""
        self.poll_result = poll_result
        self.poll_calls: list[float | None] = []

    def send(self, payload: object) -> None:
        command = getattr(payload, "command", None)
        if isinstance(command, str):
            self.sent_commands.append(command)
        request_id = getattr(payload, "request_id", None)
        if isinstance(request_id, str):
            self.last_request_id = request_id

    def poll(self, timeout: float | None = None) -> bool:
        self.poll_calls.append(timeout)
        return self.poll_result

    def recv(self) -> WorkerBackendResponse:
        return WorkerBackendResponse(
            request_id=self.last_request_id,
            kind="result",
            output_payload={"shutdown": True},
        )

    def close(self) -> None:
        self.closed = True


class _FakeHandle:
    def __init__(
        self,
        *,
        is_alive: bool = True,
        poll_result: bool = True,
        join_stops: bool = True,
    ) -> None:
        self.account_id = 2
        self.process = _FakeProcess(is_alive=is_alive, join_stops=join_stops)
        self.connection = _FakeConnection(poll_result=poll_result)
        self.request_lock = Lock()


def test_manager_recreates_dead_worker_before_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    """manager 不应复用已死亡的 worker handle。"""
    manager = WorkerBackendManager()
    dead_handle = _FakeHandle(is_alive=False)
    manager._workers[2] = dead_handle

    created: list[_FakeHandle] = []

    def fake_spawn_worker(account_id: int) -> _FakeHandle:
        assert account_id == 2
        handle = _FakeHandle(is_alive=True)
        created.append(handle)
        return handle

    monkeypatch.setattr(manager, "_spawn_worker", fake_spawn_worker)

    handle = manager._get_or_create_worker(account_id=2)

    assert handle is created[0]
    assert dead_handle.connection.closed is True


def test_manager_shutdown_all_workers_joins_processes() -> None:
    """shutdown_all 应发送关闭请求并清空 worker 缓存。"""
    manager = WorkerBackendManager()
    handle = _FakeHandle(is_alive=True)
    manager._workers[2] = handle

    manager.shutdown_all()

    assert manager._workers == {}
    assert handle.connection.sent_commands == ["shutdown"]
    assert handle.connection.closed is True
    assert handle.process.join_calls == [2.0]
    assert handle.process.terminate_called is False


def _execute_request() -> WorkerBackendRequest:
    return WorkerBackendRequest(
        request_id="req-exec",
        command="execute_trade",
        account_payload={},
        execution_id=None,
        payload={},
    )


def test_request_blocking_polls_with_configured_timeout() -> None:
    """正常响应时应先按配置超时 poll，再 recv 返回响应。"""
    manager = WorkerBackendManager(execute_recv_timeout=1.5)
    handle = _FakeHandle(is_alive=True, poll_result=True)
    manager._workers[2] = handle

    response = manager._request_blocking(2, _execute_request(), timeout=1.5)

    assert response.request_id == "req-exec"
    assert handle.connection.poll_calls == [1.5]
    assert handle.process.terminate_called is False
    assert manager._workers[2] is handle


def test_request_blocking_timeout_force_kills_and_releases_lock() -> None:
    """worker 存活但卡死（poll 超时）应强制终止进程、移出注册表并释放请求锁。"""
    manager = WorkerBackendManager()
    handle = _FakeHandle(is_alive=True, poll_result=False)
    manager._workers[2] = handle

    with pytest.raises(WorkerBackendTimeoutError):
        manager._request_blocking(2, _execute_request(), timeout=0.01)

    # 进程被强制终止且从注册表移除，避免下次复用卡死 worker。
    assert handle.process.terminate_called is True
    assert manager._workers == {}
    # request_lock 必须已释放，否则该账户 worker 将永久不可用。
    assert handle.request_lock.acquire(blocking=False) is True
    handle.request_lock.release()


def test_execute_trade_worker_timeout_follows_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """调仓 worker 外层等待应使用账户执行超时并追加 IPC 余量。"""
    manager = WorkerBackendManager()
    account = build_account(id=2, execution_timeout=180)
    standard_input = type("StandardInput", (), {"execution_timeout": 180})()
    captured_timeouts: list[float] = []

    async def fake_to_thread(func: object, *args: object) -> WorkerBackendResponse:
        del func
        captured_timeouts.append(float(args[-1]))
        request = args[-2]
        assert isinstance(request, WorkerBackendRequest)
        return WorkerBackendResponse(request_id=request.request_id, kind="result", output_payload={})

    expected = object()
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(manager, "_handle_response", lambda response: expected)

    result = asyncio.run(
        manager.execute_trade(
            account=account,
            standard_input=standard_input,  # type: ignore[arg-type]
            standard_input_dict={"execution_timeout": 180},
            audit_input={},
            strategy_config=[],
            execution_id="exec-1",
            trigger_source="manual",
            cleanup=True,
        )
    )

    assert result is expected
    assert captured_timeouts == [240.0]


def test_empty_positions_worker_timeout_follows_clear_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """清仓 worker 外层等待应使用清仓自己的执行超时并追加 IPC 余量。"""
    manager = WorkerBackendManager()
    account = build_account(id=2, execution_timeout=180)
    captured_timeouts: list[float] = []

    async def fake_to_thread(func: object, *args: object) -> WorkerBackendResponse:
        del func
        captured_timeouts.append(float(args[-1]))
        request = args[-2]
        assert isinstance(request, WorkerBackendRequest)
        return WorkerBackendResponse(request_id=request.request_id, kind="result", output_payload={})

    expected = object()
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(manager, "_handle_response", lambda response: expected)

    result = asyncio.run(
        manager.empty_positions(
            account=account,
            empty_kwargs={"execution_timeout": 90},
            audit_input={},
            execution_id="exec-clear-1",
        )
    )

    assert result is expected
    assert captured_timeouts == [150.0]


def test_dispose_handle_shutdown_timeout_falls_back_to_terminate() -> None:
    """shutdown 确认超时时不得永久阻塞，应回退到强制终止进程。"""
    manager = WorkerBackendManager(shutdown_recv_timeout=0.01)
    handle = _FakeHandle(is_alive=True, poll_result=False, join_stops=False)

    manager._dispose_handle(handle)

    assert handle.connection.sent_commands == ["shutdown"]
    assert handle.connection.closed is True
    assert handle.process.terminate_called is True


def test_manager_maps_structured_error_to_failed_output() -> None:
    """结构化错误响应应转换为失败输出，而不是抛出裸字符串异常。"""
    response = WorkerBackendResponse(
        request_id="req-1",
        kind="error",
        channel_type=TradeChannel.CTP,
        error=WorkerBackendErrorPayload(
            type="runtime_error",
            message="boom",
            retryable=False,
        ),
    )

    output = WorkerBackendManager._handle_response(response)

    assert output.success is False
    assert output.status == ExecutionStatus.FAILED
    assert output.channel_type == TradeChannel.CTP
    assert output.get_error_message() == "boom"
    assert output.extra["worker_error"] == {
        "type": "runtime_error",
        "message": "boom",
        "retryable": False,
    }

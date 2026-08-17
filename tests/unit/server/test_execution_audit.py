"""执行审计持久化与同步封装器的测试。"""

import asyncio
from types import TracebackType
from typing import cast

import pytest
from sqlalchemy.exc import IntegrityError

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import (
    ExecutionArtifactType,
    ExecutionEventStatus,
    ExecutionEventType,
    ExecutionReasonFamily,
)
from axile.server import execution_audit
from axile.server.db.models import ExecutionEvent


class _FakeSession:
    commit_error: Exception | None
    rollback_called: bool
    commit_called: bool

    def __init__(self, commit_error: Exception | None = None) -> None:
        """构造一个可选提交失败的伪异步会话。"""
        self.commit_error = commit_error
        self.added: list[object] = []
        self.rollback_called = False
        self.commit_called = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_called = True
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollback_called = True


def test_build_event_uid_is_stable_and_sensitive_to_seq() -> None:
    """相同输入生成的事件 uid 应保持稳定。"""
    first = execution_audit.build_event_uid(
        "exec-1",
        ExecutionEventType.ORDER_SUBMITTED,
        symbol="ETHUSDT",
        intent_id="exec-1:ETHUSDT",
        order_id="123",
        seq=1,
    )
    second = execution_audit.build_event_uid(
        "exec-1",
        ExecutionEventType.ORDER_SUBMITTED,
        symbol="ETHUSDT",
        intent_id="exec-1:ETHUSDT",
        order_id="123",
        seq=1,
    )
    changed = execution_audit.build_event_uid(
        "exec-1",
        ExecutionEventType.ORDER_SUBMITTED,
        symbol="ETHUSDT",
        intent_id="exec-1:ETHUSDT",
        order_id="123",
        seq=2,
    )

    assert first == second
    assert first != changed


def test_append_execution_event_persists_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应通过异步会话封装器持久化 execution 事件。"""
    fake_session = _FakeSession()
    monkeypatch.setattr(execution_audit, "SessionLocal", lambda: fake_session)

    result = asyncio.run(
        execution_audit.append_execution_event(
            execution_id="exec-1",
            account_id=1,
            channel=TradeChannel.CTP,
            algorithm="SINGLE-MAKER",
            event_type=ExecutionEventType.EXECUTION_STARTED,
            status=ExecutionEventStatus.INFO,
            reason_family=ExecutionReasonFamily.SYSTEM,
            reason_code="COMMON.EXECUTION_STARTED",
            seq=1,
            details={"debug": {"source": "test"}},
        )
    )

    assert result is True
    assert fake_session.commit_called is True
    assert len(fake_session.added) == 1
    event = cast(ExecutionEvent, fake_session.added[0])
    assert event.execution_id == "exec-1"
    assert event.reason_code == "COMMON.EXECUTION_STARTED"
    assert event.details == {"debug": {"source": "test"}}


def test_append_execution_event_ignores_duplicate_event_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """事务回滚后，应忽略重复的事件 id。"""
    duplicate_error = IntegrityError(
        "INSERT INTO execution_event",
        {},
        Exception("UNIQUE constraint failed: execution_event.event_uid"),
    )
    fake_session = _FakeSession(commit_error=duplicate_error)
    monkeypatch.setattr(execution_audit, "SessionLocal", lambda: fake_session)

    result = asyncio.run(
        execution_audit.append_execution_event(
            execution_id="exec-1",
            account_id=1,
            channel=TradeChannel.CTP,
            algorithm="SINGLE-MAKER",
            event_type=ExecutionEventType.SYMBOL_SKIPPED,
            status=ExecutionEventStatus.WARNING,
            reason_family=ExecutionReasonFamily.MARKET_RULE,
            reason_code="EXTERNAL.BELOW_MIN_NOTIONAL",
            symbol="ETHUSDT",
            seq=2,
        )
    )

    assert result is False
    assert fake_session.rollback_called is True


def test_append_execution_artifact_ignores_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """事务回滚后，应忽略重复的附件 key。"""
    duplicate_error = IntegrityError(
        "INSERT INTO execution_artifact",
        {},
        Exception("UNIQUE constraint failed: execution_artifact.execution_id, execution_artifact.artifact_type"),
    )
    fake_session = _FakeSession(commit_error=duplicate_error)
    monkeypatch.setattr(execution_audit, "SessionLocal", lambda: fake_session)

    result = asyncio.run(
        execution_audit.append_execution_artifact(
            execution_id="exec-1",
            artifact_type=ExecutionArtifactType.EXECUTION_SUMMARY,
            content={"summary": {"filled": 1}},
        )
    )

    assert result is False
    assert fake_session.rollback_called is True


def test_append_execution_event_sync_creates_coroutine_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应延迟构造协程，直到同步运行器真正执行它。"""
    called = False

    async def fake_append_execution_event(**_kwargs: object) -> bool:
        nonlocal called
        called = True
        return True

    def fake_run_coroutine_sync(factory: object) -> bool:
        assert callable(factory)
        return True

    monkeypatch.setattr(
        execution_audit,
        "append_execution_event",
        fake_append_execution_event,
    )
    monkeypatch.setattr(execution_audit, "_run_coroutine_sync", fake_run_coroutine_sync)

    result = execution_audit.append_execution_event_sync(
        execution_id="exec-1",
        account_id=1,
        channel=TradeChannel.CTP,
        algorithm="SINGLE-MAKER",
        event_type=ExecutionEventType.EXECUTION_STARTED,
        status=ExecutionEventStatus.INFO,
        reason_family=ExecutionReasonFamily.SYSTEM,
        reason_code="COMMON.EXECUTION_STARTED",
    )

    assert result is True
    assert called is False


def test_append_execution_artifact_sync_creates_coroutine_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应延迟构造附件协程，直到同步运行器真正执行它。"""
    called = False

    async def fake_append_execution_artifact(**_kwargs: object) -> bool:
        nonlocal called
        called = True
        return True

    def fake_run_coroutine_sync(factory: object) -> bool:
        assert callable(factory)
        return True

    monkeypatch.setattr(
        execution_audit,
        "append_execution_artifact",
        fake_append_execution_artifact,
    )
    monkeypatch.setattr(execution_audit, "_run_coroutine_sync", fake_run_coroutine_sync)

    result = execution_audit.append_execution_artifact_sync(
        execution_id="exec-1",
        artifact_type=ExecutionArtifactType.EXECUTION_SUMMARY,
        content={"summary": {"filled": 1}},
    )

    assert result is True
    assert called is False


def test_run_coroutine_sync_returns_value_without_running_loop() -> None:
    """无运行中事件循环时应正常执行协程并返回结果。"""

    async def _ok() -> str:
        return "done"

    assert execution_audit._run_coroutine_sync(lambda: _ok()) == "done"


def test_run_coroutine_sync_times_out_without_running_loop() -> None:
    """无 loop 分支：协程挂起应在超时内抛 TimeoutError，而非永久阻塞。"""

    async def _hang() -> None:
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        execution_audit._run_coroutine_sync(lambda: _hang(), timeout=0.1)


def test_run_coroutine_sync_times_out_with_running_loop() -> None:
    """有 loop 分支：从运行中的事件循环同步调用，挂起协程也应在超时内抛 TimeoutError。"""

    async def _hang() -> None:
        await asyncio.sleep(5)

    async def _driver() -> None:
        # 在运行中的 loop 内调用，触发临时线程分支。
        execution_audit._run_coroutine_sync(lambda: _hang(), timeout=0.1)

    with pytest.raises(TimeoutError):
        asyncio.run(_driver())


def test_run_coroutine_sync_join_backstop_fires_when_thread_wont_die(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 loop 分支：协程不可取消时，join 兜底应让调用方脱身而非永久冻结。"""
    import time

    monkeypatch.setattr(execution_audit, "_AUDIT_JOIN_GRACE_SECONDS", 0.05)

    async def _blocking() -> None:
        # 阻塞临时线程的事件循环，wait_for 定时器无法触发，模拟不可取消的挂起。
        time.sleep(1.0)

    async def _driver() -> None:
        execution_audit._run_coroutine_sync(lambda: _blocking(), timeout=0.1)

    with pytest.raises(TimeoutError, match="临时线程未在宽限内结束"):
        asyncio.run(_driver())


def test_append_execution_event_sync_swallows_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """审计写入超时应被吞成 False（尽力而为），不向调用方抛异常拖死执行。"""

    def _raise_timeout(_factory: object) -> bool:
        raise TimeoutError("audit db hang")

    monkeypatch.setattr(execution_audit, "_run_coroutine_sync", _raise_timeout)

    result = execution_audit.append_execution_event_sync(
        execution_id="exec-1",
        account_id=1,
        channel=TradeChannel.CTP,
        algorithm="SINGLE-MAKER",
        event_type=ExecutionEventType.EXECUTION_STARTED,
        status=ExecutionEventStatus.INFO,
        reason_family=ExecutionReasonFamily.SYSTEM,
        reason_code="COMMON.EXECUTION_STARTED",
    )

    assert result is False


def test_append_execution_artifact_sync_swallows_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """附件写入超时同样应被吞成 False。"""

    def _raise_timeout(_factory: object) -> bool:
        raise TimeoutError("audit db hang")

    monkeypatch.setattr(execution_audit, "_run_coroutine_sync", _raise_timeout)

    result = execution_audit.append_execution_artifact_sync(
        execution_id="exec-1",
        artifact_type=ExecutionArtifactType.EXECUTION_SUMMARY,
        content={"summary": {"filled": 1}},
    )

    assert result is False

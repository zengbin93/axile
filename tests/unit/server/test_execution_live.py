"""执行实时态广播中枢（``axile.server.execution.live``）测试。"""

import asyncio

from axile.domain.execution import ExecutionEventType
from axile.server.execution.live import ExecutionLiveHub, phase_of


def test_phase_of_maps_lifecycle_to_phases() -> None:
    """事件类型应映射到对应阶段；不推进阶段的事件返回 None。"""
    assert phase_of(ExecutionEventType.EXECUTION_STARTED) == "triggered"
    assert phase_of(ExecutionEventType.INPUT_SNAPSHOTTED) == "snapshot"
    assert phase_of(ExecutionEventType.TARGET_COMPUTED) == "planning"
    assert phase_of(ExecutionEventType.ORDER_SUBMITTED) == "executing"
    assert phase_of(ExecutionEventType.EXECUTION_COMPLETED) == "settling"
    assert phase_of(ExecutionEventType.EXECUTION_TERMINATION_REQUESTED) is None
    # 接受字符串值输入。
    assert phase_of("target_computed") == "planning"


def test_publish_advances_phase_monotonically() -> None:
    """阶段只前进不回退：晚到的靠前事件不应把阶段拉回。"""

    async def scenario() -> dict[str, object] | None:
        hub = ExecutionLiveHub()
        hub.bind_loop(asyncio.get_running_loop())
        hub.publish(execution_id="e1", account_id=7, event_type=ExecutionEventType.EXECUTION_STARTED, kind="rebalance")
        hub.publish(execution_id="e1", account_id=7, event_type=ExecutionEventType.TARGET_COMPUTED)
        # 回退事件：阶段应保持在更靠后的 planning。
        hub.publish(execution_id="e1", account_id=7, event_type=ExecutionEventType.EXECUTION_STARTED)
        return hub.progress_for(7)

    progress = asyncio.run(scenario())
    assert progress is not None
    assert progress["phase"] == "planning"
    assert progress["status"] == "running"
    assert progress["kind"] == "rebalance"


def test_subscribe_receives_frames() -> None:
    """订阅者应按事件收到广播帧，含账户、执行、阶段。"""

    async def scenario() -> list[dict[str, object]]:
        hub = ExecutionLiveHub()
        hub.bind_loop(asyncio.get_running_loop())
        received: list[dict[str, object]] = []

        async def consume() -> None:
            async with hub.subscribe() as queue:
                for _ in range(2):
                    received.append(await asyncio.wait_for(queue.get(), timeout=1.0))

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.02)  # 让订阅者先进入等待
        hub.publish(execution_id="e2", account_id=3, event_type=ExecutionEventType.EXECUTION_STARTED)
        hub.publish(execution_id="e2", account_id=3, event_type=ExecutionEventType.TARGET_COMPUTED)
        await task
        return received

    received = asyncio.run(scenario())
    assert [f["phase"] for f in received] == ["triggered", "planning"]
    assert all(f["account_id"] == 3 for f in received)
    assert all(f["execution_id"] == "e2" for f in received)


def test_snapshot_lists_running_and_terminal_marks_done() -> None:
    """snapshot 只列在跑的；终态标记后进度置为终态状态并移出在跑集。"""

    async def scenario() -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object] | None]:
        hub = ExecutionLiveHub()
        hub.bind_loop(asyncio.get_running_loop())
        hub.publish(execution_id="e3", account_id=5, event_type=ExecutionEventType.EXECUTION_STARTED)
        running_before = hub.snapshot()
        hub.publish(execution_id="e3", account_id=5, event_type=ExecutionEventType.EXECUTION_FAILED)
        running_after = hub.snapshot()
        return running_before, running_after, hub.progress_for(5)

    running_before, running_after, progress = asyncio.run(scenario())
    assert len(running_before) == 1
    assert running_before[0]["account_id"] == 5
    assert running_before[0]["status"] == "running"
    assert running_after == []
    assert progress is not None
    assert progress["status"] == "failed"
    assert progress["phase"] == "settling"

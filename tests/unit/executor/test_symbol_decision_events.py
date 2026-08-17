"""symbol 级审计事件补发与整体状态推导升级的测试。"""

from __future__ import annotations

from typing import Any

from axile.domain.execution import ExecutionEventStatus, ExecutionEventType
from axile.executor.execution_engine import ExecutionEngine, _derive_dispatch_status
from axile.executor.models.execution_result import AlgorithmResult, ExecutionStatus
from axile.executor.models.unified_input import UnifiedStandardInput


def _standard_input() -> UnifiedStandardInput:
    return UnifiedStandardInput.from_dict(
        {
            "channel_type": "ctp",
            "account_config": {"broker_id": "9999", "investor_id": "test", "password": "test"},
            "curr_target": {"BTCUSDT": 0.1},
            "algorithm": {"method": "SINGLE-MAKER", "params": {"max_wait_seconds": 60}},
            "extra": {"audit": {"execution_id": "exec-x", "account_id": 1, "algorithm": "SINGLE-MAKER"}},
        }
    )


class _FakeRuntime:
    """仅捕获 emit_audit_event 调用的假运行时。"""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit_audit_event(self, **kwargs: Any) -> bool:
        self.events.append(kwargs)
        return True


def test_emit_symbol_decision_events_covers_each_symbol() -> None:
    """失败/跳过/成功品种应分别补发带正确状态与错误的 symbol 事件。"""
    runtime = _FakeRuntime()
    engine = ExecutionEngine(object(), runtime=runtime)  # type: ignore[arg-type]
    results = [
        AlgorithmResult(symbol="ETHUSDT", algorithm="SINGLE-MAKER", status=ExecutionStatus.FAILED, error="boom"),
        AlgorithmResult(symbol="BTCUSDT", algorithm="SINGLE-MAKER", status=ExecutionStatus.NOOP),
        AlgorithmResult(symbol="SOLUSDT", algorithm="SINGLE-MAKER", status=ExecutionStatus.SUCCEEDED),
    ]

    engine._emit_symbol_decision_events(_standard_input(), results)

    by_symbol = {event["symbol"]: event for event in runtime.events}
    assert len(by_symbol) == 3

    eth = by_symbol["ETHUSDT"]
    assert eth["event_type"] == ExecutionEventType.SYMBOL_DECISION_MADE
    assert eth["status"] == ExecutionEventStatus.ERROR
    assert eth["reason_code"] == "COMMON.SYMBOL_DECISION_MADE"
    assert eth["details"]["debug"]["error"] == "boom"

    btc = by_symbol["BTCUSDT"]
    assert btc["event_type"] == ExecutionEventType.SYMBOL_SKIPPED
    assert btc["status"] == ExecutionEventStatus.SUCCESS
    assert btc["reason_code"] == "COMMON.SYMBOL_SKIPPED"
    assert "debug" not in btc["details"]

    sol = by_symbol["SOLUSDT"]
    assert sol["event_type"] == ExecutionEventType.SYMBOL_DECISION_MADE
    assert sol["status"] == ExecutionEventStatus.SUCCESS


def _results(*statuses: ExecutionStatus) -> dict[str, AlgorithmResult]:
    return {f"S{i}": AlgorithmResult(symbol=f"S{i}", algorithm="A", status=status) for i, status in enumerate(statuses)}


def test_derive_dispatch_status_failed_when_no_success() -> None:
    """失败与阻塞混合、没有任何成功时，整体应判 FAILED 而非 PARTIAL。"""
    status = _derive_dispatch_status(_results(ExecutionStatus.FAILED, ExecutionStatus.BLOCKED))
    assert status == ExecutionStatus.FAILED


def test_derive_dispatch_status_partial_when_some_success() -> None:
    """有失败也有成功时，整体应判 PARTIAL。"""
    status = _derive_dispatch_status(_results(ExecutionStatus.FAILED, ExecutionStatus.SUCCEEDED))
    assert status == ExecutionStatus.PARTIAL


def test_derive_dispatch_status_all_failed() -> None:
    """全部失败时整体判 FAILED。"""
    status = _derive_dispatch_status(_results(ExecutionStatus.FAILED, ExecutionStatus.FAILED))
    assert status == ExecutionStatus.FAILED

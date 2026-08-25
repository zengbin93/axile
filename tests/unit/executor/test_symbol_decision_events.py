"""symbol 级审计事件补发与整体状态推导升级的测试。"""

from __future__ import annotations

from typing import Any

from axile.domain.execution import ExecutionEventStatus, ExecutionEventType, ExecutionReasonFamily
from axile.executor.execution_engine import ExecutionEngine, _derive_dispatch_status
from axile.executor.models.execution_result import AlgorithmResult, ExecutionStatus
from axile.executor.models.unified_input import UnifiedStandardInput


def _standard_input() -> UnifiedStandardInput:
    return UnifiedStandardInput.from_dict(
        {
            "channel_type": "ctp",
            "account_config": {
                "broker_id": "9999",
                "investor_id": "test",
                "password": "test",
                "td_front": "tcp://td:1",
                "md_front": "tcp://md:2",
                "app_id": "app",
                "auth_code": "auth",
            },
            "curr_target": {"rb2610": 0.1},
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
        AlgorithmResult(symbol="ag2612", algorithm="SINGLE-MAKER", status=ExecutionStatus.FAILED, error="boom"),
        AlgorithmResult(symbol="rb2610", algorithm="SINGLE-MAKER", status=ExecutionStatus.NOOP),
        AlgorithmResult(symbol="au2612", algorithm="SINGLE-MAKER", status=ExecutionStatus.SUCCEEDED),
    ]

    engine._emit_symbol_decision_events(_standard_input(), results)

    by_symbol = {event["symbol"]: event for event in runtime.events}
    assert len(by_symbol) == 3

    ag = by_symbol["ag2612"]
    assert ag["event_type"] == ExecutionEventType.SYMBOL_DECISION_MADE
    assert ag["status"] == ExecutionEventStatus.ERROR
    assert ag["reason_code"] == "COMMON.SYMBOL_DECISION_MADE"
    assert ag["details"]["debug"]["error"] == "boom"

    rb = by_symbol["rb2610"]
    assert rb["event_type"] == ExecutionEventType.SYMBOL_SKIPPED
    assert rb["status"] == ExecutionEventStatus.SUCCESS
    assert rb["reason_code"] == "COMMON.SYMBOL_SKIPPED"
    assert "debug" not in rb["details"]

    au = by_symbol["au2612"]
    assert au["event_type"] == ExecutionEventType.SYMBOL_DECISION_MADE
    assert au["status"] == ExecutionEventStatus.SUCCESS


def test_emit_ctp_session_precheck_as_market_rule_warning() -> None:
    runtime = _FakeRuntime()
    engine = ExecutionEngine(object(), runtime=runtime)  # type: ignore[arg-type]

    engine._emit_symbol_decision_events(
        _standard_input(),
        [
            AlgorithmResult(
                symbol="ag2609C5000",
                algorithm="SINGLE-MAKER",
                status=ExecutionStatus.BLOCKED,
                error="CTP.SESSION.NO_SESSION_TABLE",
                memory={"precheck_reason_code": "CTP.SESSION.NO_SESSION_TABLE"},
            )
        ],
    )

    event = runtime.events[0]
    assert event["event_type"] == ExecutionEventType.SYMBOL_DECISION_MADE
    assert event["status"] == ExecutionEventStatus.WARNING
    assert event["reason_family"] == ExecutionReasonFamily.MARKET_RULE
    assert event["reason_code"] == "CTP.SESSION.NO_SESSION_TABLE"


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

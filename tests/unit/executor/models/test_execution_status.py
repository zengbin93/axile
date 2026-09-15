import pytest

from axile.executor.algorithms.utils.outcome import summarize_outcome
from axile.executor.constants.order_status import OrderStatus
from axile.executor.execution_engine import _derive_dispatch_status
from axile.executor.models.execution_result import AlgorithmResult, ExecutionStatus
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder


def test_summarize_outcome_uses_only_explicit_facts() -> None:
    result = summarize_outcome(0, 0, 1, [], [], explicit_blocked_error="当前不在交易时段")
    assert result["status"] == ExecutionStatus.BLOCKED
    assert result["error"] == "当前不在交易时段"


def test_summarize_outcome_does_not_need_debug_payload() -> None:
    result = summarize_outcome(0, 0, 1, [], [])
    assert result["status"] == ExecutionStatus.FAILED


@pytest.mark.parametrize(
    "start,final,target,error,blocked,expected",
    [
        (1, 1, 1, None, None, "NOOP"),
        (0, 1, 1, None, None, "SUCCEEDED"),
        (0, 0, 1, None, "交易时段关闭", "BLOCKED"),
        (0, 1, 2, None, "交易时段关闭", "PARTIAL"),
        (0, float("nan"), 1, None, None, "FAILED"),
        (0, 0, 1, "报单失败", "交易时段关闭", "FAILED"),
        (0, 1, 1, "撤单失败", None, "PARTIAL"),
    ],
)
def test_result_status_matrix(start, final, target, error, blocked, expected):
    result = summarize_outcome(start, final, target, [], [], error, blocked)
    assert result["status"] == expected
    assert not {"outcome", "outcome_reason", "diagnostics"} & result.keys()


@pytest.mark.parametrize(
    "status,final,expected",
    [
        (OrderStatus.FILLED, 1, "SUCCEEDED"),
        (OrderStatus.PENDING, 1, "PARTIAL"),
        (OrderStatus.REJECTED, 0, "PARTIAL"),
        (OrderStatus.CANCELED, 0, "PARTIAL"),
        (OrderStatus.CANCELED, float("nan"), "PARTIAL"),
    ],
)
def test_existing_orders_are_progress_and_require_confirmed_terminal_state(status, final, expected):
    order = UnifiedOrder(
        order_id="1",
        symbol="A",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1,
        price=10,
        status=status,
    )
    result = summarize_outcome(0, final, 1, [order], [], explicit_blocked_error="限制")
    assert result["status"] == expected


def test_debug_fields_never_change_successful_result():
    facts = summarize_outcome(0, 1, 1, [], [])
    result = AlgorithmResult(**facts, memory={"error_count": 10, "last_error": "失败", "skipped_count": 99})
    assert result.status == "SUCCEEDED"
    assert result.error is None


@pytest.mark.parametrize("status", [ExecutionStatus.BLOCKED, ExecutionStatus.FAILED])
def test_noop_does_not_count_as_progress_in_aggregate(status):
    results = {"A": AlgorithmResult(status=ExecutionStatus.NOOP), "B": AlgorithmResult(status=status, error="明确原因")}
    assert _derive_dispatch_status(results) == status

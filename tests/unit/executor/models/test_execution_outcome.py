"""执行过程错误与持仓未到位的独立展示结论。"""

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.utils.outcome import summarize_outcome
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.execution_result import AlgorithmResult, ExecutionOutcome, ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput


@pytest.mark.parametrize(
    "outcomes,expected",
    [
        (["completed"], "completed"),
        (["completed", "not_reached"], "not_reached"),
        (["not_reached", "not_reached"], "not_reached"),
        (["completed", "error"], "error"),
        (["error", "unknown"], "error"),
        (["completed", "blocked"], "not_reached"),
        (["blocked", "blocked"], "blocked"),
        (["terminated"], "terminated"),
        (["completed", "unknown"], "unknown"),
        ([], "unknown"),
    ],
)
def test_output_conclusion_uses_explicit_symbol_evidence(outcomes, expected):
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets(available_cash=1, total_asset=1, market_value=0, positions=[]),
        channel_type=TradeChannel.CTP,
        status=ExecutionStatus.FAILED,
        error="2 个品种执行未成功",
        symbol_results={
            str(i): AlgorithmResult(
                outcome=ExecutionOutcome(value), outcome_reason="连接断开" if value == "error" else None
            )
            for i, value in enumerate(outcomes)
        },
    )
    assert output.outcome.value == expected
    assert output.success is False  # 展示结论不改变旧控制口径。
    if expected == "error":
        assert output.outcome_reason == "连接断开"
    encoded = output.model_dump_json()
    assert UnifiedStandardOutput.model_validate_json(encoded).outcome == output.outcome


def test_normal_shortfall_and_process_error_are_different():
    shortfall = summarize_outcome(0, 1, 2, [], [], {})
    assert shortfall["outcome"] == ExecutionOutcome.NOT_REACHED
    assert shortfall["final_volume"] == 1
    failure = summarize_outcome(0, 1, 2, [], [], {"error": "连接断开"})
    assert failure["outcome"] == ExecutionOutcome.ERROR
    assert failure["outcome_reason"] == "连接断开"


def test_unknown_final_position_is_not_zero_or_success():
    result = summarize_outcome(0, float("nan"), 0, [], [], {})
    assert result["outcome"] == ExecutionOutcome.UNKNOWN
    assert result["final_volume"] is None


def test_rejected_order_is_process_error_even_if_target_reached():
    order = UnifiedOrder(
        order_id="1",
        symbol="m2701",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1,
        price=1,
        status=OrderStatus.REJECTED,
    )
    result = summarize_outcome(0, 1, 1, [order], [], {})
    assert result["outcome"] == ExecutionOutcome.ERROR
    assert result["outcome_reason"] == "存在拒单"

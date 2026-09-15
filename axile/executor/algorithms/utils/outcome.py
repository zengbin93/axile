"""以最终持仓与订单终态共同判定算法结果，禁止把提交成功视作达标。"""

from math import isclose, isfinite
from typing import TypedDict

from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.execution_result import ExecutionOutcome, ExecutionStatus, outcome_from_status
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder


class OutcomeSummary(TypedDict):
    """算法结果的明确状态、错误与可序列化持仓字段；outcome 恒等于 f(status)。"""

    status: ExecutionStatus
    error: str | None
    final_volume: float | None
    outcome: ExecutionOutcome
    outcome_reason: str | None


def summarize_outcome(
    start: float,
    final: float,
    target: float,
    orders: list[UnifiedOrder],
    trades: list[TradeRecord],
    explicit_error: str | None = None,
    explicit_blocked_error: str | None = None,
) -> OutcomeSummary:
    """以订单、成交、持仓和明确错误聚合结果，绝不扫描调试数据。"""
    terminal = all(OrderStatus.is_completed(order.status) for order in orders)
    completed = isfinite(final) and isclose(final, target, rel_tol=0, abs_tol=1e-9)
    progress = bool(orders or trades) or (isfinite(final) and final != start)
    rejected = any(order.status == OrderStatus.REJECTED for order in orders)
    error = explicit_error
    if rejected and error is None:
        error = "报单被拒绝"
    if not terminal and error is None:
        error = "订单最终状态尚未确认（含撤单结果未知）"
    if not isfinite(final) and error is None:
        error = "最终持仓尚未确认"
    if completed and error is None:
        status = ExecutionStatus.NOOP if start == target and not orders else ExecutionStatus.SUCCEEDED
    elif error is None and not progress and explicit_blocked_error:
        status, error = ExecutionStatus.BLOCKED, explicit_blocked_error
    else:
        status = ExecutionStatus.PARTIAL if progress else ExecutionStatus.FAILED
        if error is None:
            error = explicit_blocked_error or f"目标未完成: 当前持仓={final}，目标持仓={target}"
    return {
        "status": status,
        "error": error,
        "final_volume": final if isfinite(final) else None,
        "outcome": outcome_from_status(status),
        "outcome_reason": error,
    }

"""以最终持仓与订单终态共同判定算法结果，禁止把提交成功视作达标。"""

from math import isclose, isfinite
from typing import Any

from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder


def summarize_outcome(
    start: float,
    final: float,
    target: float,
    orders: list[UnifiedOrder],
    trades: list[TradeRecord],
    details: Any,
) -> dict[str, Any]:
    """保守聚合错误、欠量及未确认终态；成交后仍有风险时返回 PARTIAL。"""
    errors = _errors(details)
    remaining = target - final
    terminal = all(OrderStatus.is_completed(order.status) for order in orders)
    completed = isfinite(final) and isclose(final, target, rel_tol=0, abs_tol=1e-9)
    rejected = any(order.status == OrderStatus.REJECTED for order in orders)
    if not terminal:
        errors.append("订单终态未确认（含撤单结果未知）")
    if rejected:
        errors.append("存在拒单")
    if not completed:
        errors.append(f"目标未完成: final={final}, target={target}, remaining={remaining}")
    filled = sum(trade.trade_volume for trade in trades)
    progress = filled > 0 or any(order.filled_volume > 0 for order in orders) or final != start
    if errors:
        status = ExecutionStatus.PARTIAL if progress else ExecutionStatus.FAILED
        if not orders and not _errors(details) and _skipped(details):
            status = ExecutionStatus.BLOCKED
    else:
        status = ExecutionStatus.NOOP if start == target and not orders else ExecutionStatus.SUCCEEDED
    return {"status": status, "error": "; ".join(errors) or None}


def _errors(details: Any) -> list[str]:
    if isinstance(details, list):
        return [error for item in details for error in _errors(item)]
    if isinstance(details, dict):
        return [str(value) for key, value in details.items() if "error" in key and value]
    return []


def _skipped(details: Any) -> bool:
    if isinstance(details, list):
        return any(_skipped(item) for item in details)
    return isinstance(details, dict) and any("skipped" in key and value for key, value in details.items())

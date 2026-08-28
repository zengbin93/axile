"""编译并执行用户提供的组合目标函数."""

from __future__ import annotations

from typing import cast

from axile.server.portfolio_function import (
    PortfolioFunctionError,
    PortfolioFunctionResult,
    calculate_portfolio_target,
    portfolio_result_from_exception,
)


async def calculate_portfolio_for_account(
    account: object,
    code: str,
    *,
    execution_id: str | None = None,
) -> PortfolioFunctionResult:
    """通过账户常驻 worker 运行自定义组合函数."""
    from axile.server.db.models import Account
    from axile.server.execution.worker_backend.manager import get_worker_backend_manager

    resolved_account = cast("Account", account)
    try:
        return await get_worker_backend_manager().calculate_portfolio(
            resolved_account,
            code,
            execution_id=execution_id,
        )
    except BaseException as exc:  # noqa: BLE001 - worker 故障也使用函数结果契约
        return portfolio_result_from_exception(exc)


__all__ = [
    "PortfolioFunctionError",
    "PortfolioFunctionResult",
    "calculate_portfolio_for_account",
    "calculate_portfolio_target",
    "portfolio_result_from_exception",
]

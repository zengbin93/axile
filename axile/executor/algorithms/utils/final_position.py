"""查询最终持仓失败时保留订单证据，不把未知仓位当成零。"""

from collections.abc import Callable

from axile.executor.algorithms.core.base import ExecutorProtocol
from axile.executor.algorithms.exceptions import execution_error_message
from axile.executor.models.unified_account_assets import UnifiedAccountAssets, is_degraded_snapshot_source
from axile.executor.termination import ExecutionTerminated


def read_final_position(
    executor: ExecutorProtocol,
    quantity: Callable[[UnifiedAccountAssets], float],
) -> tuple[UnifiedAccountAssets, float, str | None]:
    """返回资产、持仓与明确查询错误；原始异常由日志保留。"""
    try:
        assets = executor.get_account_assets()
        if is_degraded_snapshot_source(assets.source):
            return assets, float("nan"), "最终持仓尚未确认"
        return assets, quantity(assets), None
    except (ExecutionTerminated, MemoryError):
        raise
    except Exception as exc:  # noqa: BLE001 - 渠道 SDK 异常不一定继承 RuntimeError
        if getattr(exc, "requires_session_recovery", False):
            raise
        executor.logger.exception("最终持仓查询失败")
        return UnifiedAccountAssets.unavailable(), float("nan"), execution_error_message(exc, "最终持仓查询")

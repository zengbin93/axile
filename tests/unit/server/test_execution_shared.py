"""执行共享辅助函数测试。"""

from axile.domain.execution import ExecutionKind
from axile.server.execution.execution_algorithms import (
    resolve_empty_positions_algorithm,
    resolve_execution_algorithm_name,
)
from axile.server.execution.execution_summaries import (
    build_execution_summary_from_symbol_results,
    count_orders_from_symbol_results,
)
from tests.unit.server._execution_test_support import build_account


def test_shared_helper_functions_cover_summary_and_algorithm_resolution() -> None:
    """共享辅助函数应覆盖摘要统计与算法解析逻辑。"""
    account = build_account(empty_positions_algorithm={"method": "SINGLE-MAKER", "params": {"max_wait_seconds": 5}})

    summary = build_execution_summary_from_symbol_results(
        {
            "symbol_results": {
                "rb2610": {"status": "SUCCEEDED", "orders": [1]},
                "ag2612": {"status": "BLOCKED", "orders": [1, 2]},
                "au2612": {"status": "FAILED", "orders": "bad"},
                "m2609": {"status": "NOOP", "orders": []},
                "SR609": "not-a-dict",
            }
        }
    )

    # symbols_succeeded 仍含 NOOP（total-failed），symbols_noop 单列以供前端区分空跑。
    assert summary == {
        "symbols_total": 5,
        "symbols_succeeded": 3,
        "symbols_failed": 2,
        "symbols_noop": 1,
    }
    assert (
        count_orders_from_symbol_results(
            {
                "symbol_results": {
                    "rb2610": {"orders": [1]},
                    "ag2612": {"orders": [1, 2]},
                    "au2612": {"orders": "bad"},
                }
            }
        )
        == 3
    )
    assert resolve_execution_algorithm_name(account, ExecutionKind.REBALANCE) == "SINGLE-MAKER"
    assert resolve_execution_algorithm_name(account, ExecutionKind.CLEAR_POSITIONS) == "SINGLE-MAKER"
    assert (
        resolve_execution_algorithm_name(
            account,
            ExecutionKind.REBALANCE,
            {"method": "CUSTOM-ALGO", "params": {}},
        )
        == "CUSTOM-ALGO"
    )
    assert resolve_empty_positions_algorithm(account) == {
        "method": "SINGLE-MAKER",
        "params": {"max_wait_seconds": 5},
    }
    assert resolve_empty_positions_algorithm(account, {"method": "OVERRIDE"}) == {"method": "OVERRIDE"}
    assert resolve_empty_positions_algorithm(build_account(empty_positions_algorithm=None)) == {
        "method": "TARGET-POS-TASK",
        "params": {},
    }

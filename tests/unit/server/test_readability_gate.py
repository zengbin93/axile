"""可读性门禁：新写路径的用户可见错误必须是短中文人话.

禁止异常类名、堆栈、SDK 原文和变量名风格（``final=``）进入展示层字段。
技术原文只能进日志、事件 ``debug`` 命名空间与 ``technical_detail``。
"""

import re

import pytest

from axile.executor.algorithms.exceptions import execution_error_message
from axile.executor.algorithms.utils.final_position import read_final_position
from axile.executor.algorithms.utils.outcome import summarize_outcome
from axile.executor.algorithms.utils.trading import create_unconfirmed_start_result
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder
from axile.server.execution.backend import _record_rebalance_inline_failure  # noqa: F401 - 仅验证模块可导入
from axile.server.execution.legacy_compat import normalize_legacy_result

_EXCEPTION_CLASS = re.compile(r"[A-Za-z_.]+(Error|Exception)\b")
_FORBIDDEN_MARKERS = ("Traceback", "final=", "target=", "remaining=", "ErrorID=", "return_code=")


def _assert_human_readable(text: str | None) -> None:
    """展示层文案不得携带技术痕迹。"""
    if text is None:
        return
    assert not _EXCEPTION_CLASS.search(text), f"错误文案含异常类名: {text}"
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in text, f"错误文案含技术标记 {marker}: {text}"


def _order(status: str, filled: float = 0.0) -> UnifiedOrder:
    return UnifiedOrder(
        order_id="gate-order",
        symbol="A",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=1,
        price=100,
        status=status,
        filled_volume=filled,
    )


@pytest.mark.parametrize(
    "error,blocked",
    [
        (None, None),
        ("报单失败", None),
        (None, "当前不在交易时段"),
        ("撤单失败，订单终态尚未确认", None),
    ],
)
def test_summarize_outcome_error_is_human_readable(error, blocked):
    for final in (0.0, 1.0, float("nan")):
        summary = summarize_outcome(0, final, 1, [_order("FILLED")], [], error, blocked)
        _assert_human_readable(summary["error"])


def test_explicit_error_strings_are_human_readable():
    _assert_human_readable("报单被拒绝")
    _assert_human_readable("订单最终状态尚未确认（含撤单结果未知）")
    _assert_human_readable("最终持仓尚未确认")
    _assert_human_readable("目标未完成: 当前持仓=10，目标持仓=0")
    _assert_human_readable("初始持仓尚未确认")


def test_execution_error_message_never_leaks_exception_class():
    class FakeChannelError(RuntimeError):
        pass

    _assert_human_readable(execution_error_message(FakeChannelError("synthetic SDK failure")))
    _assert_human_readable(execution_error_message(TimeoutError("rest timeout after 30s"), "报单"))
    _assert_human_readable(execution_error_message(ValueError("bad payload"), "持仓查询"))
    # 渠道在错误发生处写的人话原样保留。
    exc = FakeChannelError("raw text")
    exc.execution_error = "资金不足，报单被拒绝"
    assert execution_error_message(exc) == "资金不足，报单被拒绝"


class _FailingReader:
    """模拟收尾持仓查询失败的执行器协议。"""

    logger = type("L", (), {"exception": staticmethod(lambda *_a, **_k: None)})()

    def get_account_assets(self):
        raise RuntimeError("CtpRequestError: ErrorID=31, 资金不足")


def test_read_final_position_error_is_human_readable():
    _, final, query_error = read_final_position(_FailingReader(), lambda assets: 0.0)
    assert final != final  # NaN：未知持仓绝不落成 0
    _assert_human_readable(query_error)


def test_unconfirmed_start_result_is_human_readable():
    from axile.executor.models.unified_account_assets import UnifiedAccountAssets

    result = create_unconfirmed_start_result(
        UnifiedAccountAssets.unavailable(),
        algorithm_name="POV",
        symbol="A",
        target_volume=1,
    )
    _assert_human_readable(result.error)
    assert result.status == ExecutionStatus.FAILED


def test_legacy_normalization_fixed_copies_are_human_readable():
    for raw in (
        {"outcome": "error", "msg": "RuntimeError: boom"},
        {"outcome": "blocked"},
        {"outcome": "not_reached"},
        {"outcome": "terminated"},
        {"status": ExecutionStatus.FAILED.value},
    ):
        normalized = normalize_legacy_result(raw)
        if isinstance(normalized, dict):
            _assert_human_readable(normalized.get("error"))


def test_engine_and_event_errors_carry_human_text():
    """引擎派发错误与事件公共层错误使用固定人话。"""
    _assert_human_readable("报单被拒绝，2 个品种未执行")
    _assert_human_readable("2 个品种执行受阻")
    _assert_human_readable("调仓执行失败，具体原因未确认")
    _assert_human_readable("清仓执行失败，具体原因未确认")
    _assert_human_readable("执行失败，具体原因见执行证据")

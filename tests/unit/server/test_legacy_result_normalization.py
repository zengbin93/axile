"""旧执行记录读时归一的契约测试：只补明确结论，不改写历史，不透传技术原文。"""

import pytest

from axile.server.execution.legacy_compat import normalize_legacy_result


def test_new_contract_record_passes_through_unchanged():
    """新记录已带 status/error/outcome，归一化不得改写任何字段。"""
    raw = {"status": "PARTIAL", "error": "剩余 1 手", "outcome": "not_reached", "symbol_results": {}}
    assert normalize_legacy_result(raw) == raw


def test_legacy_outcome_backfills_status_without_override():
    """旧 outcome 补出 status；已有 status 一律不覆盖。"""
    assert normalize_legacy_result({"outcome": "error"})["status"] == "FAILED"
    assert normalize_legacy_result({"outcome": "completed"})["status"] == "SUCCEEDED"
    assert normalize_legacy_result({"outcome": "not_reached"})["status"] == "PARTIAL"
    assert normalize_legacy_result({"outcome": "blocked"})["status"] == "BLOCKED"
    # 冲突时以明确 status 为准，不翻转历史结论。
    assert normalize_legacy_result({"status": "SUCCEEDED", "outcome": "error"})["status"] == "SUCCEEDED"


def test_terminated_outcome_backfills_task_status():
    assert normalize_legacy_result({"outcome": "terminated"})["task_status"] == "TERMINATED"


def test_status_backfills_outcome_for_display():
    """带 status 无 outcome 的记录反向补齐，展示层不再需要 legacy 分支。"""
    assert normalize_legacy_result({"status": "NOOP"})["outcome"] == "completed"
    assert normalize_legacy_result({"status": "FAILED"})["outcome"] == "error"


def test_human_legacy_message_becomes_error():
    """说人话的遗留文案沿用，不丢信息。"""
    raw = {"outcome": "error", "msg": "调仓执行失败，具体原因未确认"}
    normalized = normalize_legacy_result(raw)
    assert normalized["error"] == "调仓执行失败，具体原因未确认"
    assert "technical_detail" not in normalized


def test_technical_legacy_text_never_reaches_error():
    """异常类名/SDK 原文只进 technical_detail，主展示用固定人话。"""
    raw = {"outcome": "error", "msg": "RuntimeError: 部分订单撤销失败: ['CTP:12345']"}
    normalized = normalize_legacy_result(raw)
    assert normalized["error"] == "执行失败，具体原因见执行证据"
    assert normalized["technical_detail"] == "RuntimeError: 部分订单撤销失败: ['CTP:12345']"


@pytest.mark.parametrize(
    "message",
    ["Traceback (most recent call last)", "下单失败: ErrorID=31, 资金不足", "查询失败 return_code=-1"],
)
def test_technical_markers_are_detected(message):
    normalized = normalize_legacy_result({"outcome": "error", "msg": message})
    assert normalized["error"] == "执行失败，具体原因见执行证据"
    assert normalized["technical_detail"] == message


def test_fixed_copy_per_outcome():
    assert normalize_legacy_result({"outcome": "blocked"})["error"] == "账户风控拦截，未执行"
    assert normalize_legacy_result({"outcome": "not_reached"})["error"] == "执行不到位"
    assert normalize_legacy_result({"outcome": "terminated"})["error"] == "执行已终止"


def test_success_records_do_not_get_fabricated_error():
    """成功态不强造错误。"""
    assert "error" not in normalize_legacy_result({"outcome": "completed"})
    assert "error" not in normalize_legacy_result({"status": "NOOP", "memory": {"message": "没有需要执行的交易"}})


def test_recursion_into_symbols_and_reconciliation():
    """symbol_results 与 reconciliation.symbols 逐层归一。"""
    raw = {
        "outcome": "not_reached",
        "symbol_results": {"rb2610": {"outcome": "error", "msg": "ValueError: bad"}},
        "reconciliation": {"symbols": [{"outcome": "blocked"}]},
    }
    normalized = normalize_legacy_result(raw)
    symbol = normalized["symbol_results"]["rb2610"]
    assert symbol["status"] == "FAILED"
    assert symbol["error"] == "执行失败，具体原因见执行证据"
    assert symbol["technical_detail"] == "ValueError: bad"
    assert normalized["reconciliation"]["symbols"][0]["status"] == "BLOCKED"


def test_non_dict_input_passthrough():
    assert normalize_legacy_result(None) is None
    assert normalize_legacy_result("text") == "text"


def test_idempotent():
    """归一化幂等：跑两遍结果一致。"""
    raw = {"outcome": "error", "msg": "RuntimeError: boom"}
    once = normalize_legacy_result(raw)
    assert normalize_legacy_result(once) == once

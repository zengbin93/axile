"""旧执行记录的读时归一：只补明确结论，不改写历史，不透传技术原文。

历史记录只带 ``outcome``/``outcome_reason``/``msg`` 时，读取方拿不到
``status``/``error`` 契约字段。本模块在序列化边界按固定映射现算补齐：

- ``status`` 仅在缺失时从旧 ``outcome`` 回填，已有明确状态一律不覆盖；
- ``error`` 仅在缺失时回填：旧文案说人话则沿用，异常类名/SDK 原文只进
  ``technical_detail``（仅审计视图可消费），主展示用固定人话兜底；
- 递归处理 ``symbol_results`` 与 ``reconciliation.symbols``。

与数据迁移的本质差异：不写库、幂等、映射修正即时全局生效。
"""

import re
from typing import Any

_STATUS_FROM_OUTCOME = {
    "completed": "SUCCEEDED",
    "not_reached": "PARTIAL",
    "error": "FAILED",
    "blocked": "BLOCKED",
}

# 反向映射：带 status 而无展示结论的记录补齐 outcome，展示层不再需要 legacy 分支。
_OUTCOME_FROM_STATUS = {value: key for key, value in _STATUS_FROM_OUTCOME.items()}
_OUTCOME_FROM_STATUS["NOOP"] = "completed"

_TERMINATED_OUTCOME = "terminated"
_TERMINATED_TASK_STATUS = "TERMINATED"

# 旧结论对应的固定人话；展示层永远拿得到可读说明。
_LEGACY_ERROR_COPY = {
    "error": "执行失败，具体原因见执行证据",
    "not_reached": "执行不到位",
    "blocked": "执行受阻，具体原因见执行证据",
    _TERMINATED_OUTCOME: "执行已终止",
}

_EXCEPTION_CLASS = re.compile(r"\b[\w.]*(Error|Exception)\b[:\s]")
_TECHNICAL_MARKERS = ("Traceback", "ErrorID=", "return_code=")


def _text(value: object) -> str | None:
    """非空字符串才视为文本。"""
    return value if isinstance(value, str) and value.strip() else None


def _is_technical_text(text: str) -> bool:
    """识别异常类名、堆栈与渠道错误码等不宜展示给用户的技术原文。

    异常类名可出现在句子中缀（如 ``错误原因: RuntimeError: ...``），用 search 全文匹配。
    """
    return bool(
        _EXCEPTION_CLASS.search(text)
        or any(marker in text for marker in _TECHNICAL_MARKERS)
        or re.fullmatch(r"(?:-?\d+|[A-Z][A-Z0-9_.]*)", text.strip())
        or text == "gm_authentication_error"
    )


def _legacy_message(raw: dict[str, Any]) -> str | None:
    """按优先级收集旧记录遗留的过程文案。"""
    memory = raw.get("memory")
    candidates = (
        raw.get("outcome_reason"),
        raw.get("msg"),
        memory.get("message") if isinstance(memory, dict) else None,
    )
    texts = [text for item in candidates if (text := _text(item))]
    return next((text for text in texts if not _is_technical_text(text)), texts[0] if texts else None)


def normalize_legacy_result(raw: object) -> object:
    """
    就地补齐旧执行结果的契约字段；新记录（已带 status/error）原样返回。

    Parameters
    ----------
    raw : object
        持久化的执行结果 JSON（通常是 ``raw_result`` 字典）。

    Returns
    -------
    object
        补齐 ``status``/``error``（必要时附 ``technical_detail``）后的浅拷贝；
        非字典输入原样返回。``reconciliation.symbols`` 是持仓证据行，不做回填。
    """
    if not isinstance(raw, dict):
        return raw
    result = dict(raw)
    outcome = result.get("outcome")

    if not _text(result.get("status")) and isinstance(outcome, str):
        result["status"] = _STATUS_FROM_OUTCOME.get(outcome)
        if outcome == _TERMINATED_OUTCOME and not _text(result.get("task_status")):
            result["task_status"] = _TERMINATED_TASK_STATUS

    if not _text(result.get("outcome")):
        status = result.get("status")
        result["outcome"] = _OUTCOME_FROM_STATUS.get(status) if isinstance(status, str) else None
        if result["outcome"] is None and result.get("task_status") == _TERMINATED_TASK_STATUS:
            result["outcome"] = _TERMINATED_OUTCOME

    if not _text(result.get("error")):
        legacy = _legacy_message(raw)
        needs_error = (
            _is_unsuccessful(result.get("status"))
            or result.get("task_status") == _TERMINATED_TASK_STATUS
            or (result.get("status") is None and legacy is not None)
        )
        if needs_error:
            if legacy is not None and not _is_technical_text(legacy):
                result["error"] = legacy
            else:
                if legacy is not None:
                    result.setdefault("technical_detail", legacy)
                # 用回填后的 outcome 取固定文案，覆盖「无结论但有状态」的记录。
                result["error"] = _LEGACY_ERROR_COPY.get(str(result.get("outcome"))) or "执行结果待确认"
    elif _is_technical_text(result["error"]):
        # 历史写入的 error 自带异常原文：原文退入 technical_detail，主展示换固定人话。
        result.setdefault("technical_detail", result["error"])
        reason = _text(result.get("outcome_reason"))
        result["error"] = (
            reason
            if reason and not _is_technical_text(reason)
            else (_LEGACY_ERROR_COPY.get(_OUTCOME_FROM_STATUS.get(str(result.get("status")), "")) or "执行结果待确认")
        )

    symbols = result.get("symbol_results")
    if isinstance(symbols, dict):
        result["symbol_results"] = {symbol: normalize_legacy_result(item) for symbol, item in symbols.items()}
    # reconciliation.symbols 是持仓证据行（before/after/reached），不是结果记录，
    # 不得对其回填 status/error——那是把结论编造进证据。
    return result


def _is_unsuccessful(status: object) -> bool:
    """仅失败类状态需要可读错误；成功态与未知态不强造结论。"""
    return status in {"FAILED", "PARTIAL", "BLOCKED", "TERMINATED"}


def normalize_execution_event_details(details: object) -> object:
    """
    旧事件 ``details.debug.error`` 读时提升为公共层 ``details.error``.

    仅提升说人话的文案；异常类名/SDK 原文留在 ``debug`` 命名空间，
    只有审计/证据视图可以消费。
    """
    if not isinstance(details, dict) or _text(details.get("error")) is not None:
        return details
    debug = details.get("debug")
    if not isinstance(debug, dict):
        return details
    error = _text(debug.get("error"))
    if error is None or _is_technical_text(error):
        return details
    return {**details, "error": error}

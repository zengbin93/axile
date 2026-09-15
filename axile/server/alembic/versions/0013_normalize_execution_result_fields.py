"""将历史明确结论补入新结果字段，并纠正与之冲突的旧成功标记。"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_STATUS = {"completed": "SUCCEEDED", "not_reached": "PARTIAL", "error": "FAILED", "blocked": "BLOCKED"}
_UNSUCCESSFUL = frozenset({"blocked", "not_reached", "error"})


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _legacy_failure(value: object) -> bool:
    """只认旧结论明确的未成功，不从错误文案或成交量推断。"""
    return (
        isinstance(value, dict)
        and value.get("outcome") in _UNSUCCESSFUL
        and value.get("status") in ("BLOCKED", "PARTIAL", "FAILED")
    )


def _normalize(value: object) -> object:
    """补齐明确旧字段，并覆盖与未成功结论冲突的成功状态。"""
    if not isinstance(value, dict):
        return value
    result = dict(value)
    outcome = value.get("outcome")
    if not _text(value.get("status")) and isinstance(outcome, str) and outcome in _STATUS:
        result["status"] = _STATUS[outcome]
    elif value.get("status") in ("NOOP", "SUCCEEDED") and isinstance(outcome, str) and outcome in _UNSUCCESSFUL:
        result["status"] = _STATUS[outcome]
    if outcome == "terminated" and not _text(value.get("task_status")):
        result["task_status"] = "TERMINATED"
    if not _text(value.get("error")):
        memory = value.get("memory")
        candidates = (
            value.get("msg"),
            memory.get("message") if isinstance(memory, dict) else None,
            value.get("outcome_reason"),
        )
        error = next((item for item in candidates if _text(item)), None)
        if error is not None:
            result["error"] = error
    if _legacy_failure(result) and "success" in result:
        result["success"] = False
    symbols = value.get("symbol_results")
    if isinstance(symbols, dict):
        result["symbol_results"] = {symbol: _normalize(item) for symbol, item in symbols.items()}
    reconciliation = value.get("reconciliation")
    if isinstance(reconciliation, dict) and isinstance(reconciliation.get("symbols"), list):
        result["reconciliation"] = {
            **reconciliation,
            "symbols": [_normalize(item) for item in reconciliation["symbols"]],
        }
    return result


def _migrate(table_name: str, column_name: str, *, records: bool) -> None:
    """按主键分批更新；记录表同时把冲突的成功标记改成失败。"""
    bind = op.get_bind()
    table = sa.table(
        table_name,
        sa.column("id", sa.Integer()),
        sa.column(column_name, sa.JSON()),
        sa.column("is_success", sa.Integer()) if records else sa.column("artifact_type", sa.String()),
    )
    column = table.c[column_name]
    last_id = -1
    while True:
        success = table.c.is_success if records else sa.literal(None)
        query = sa.select(table.c.id, column, success).where(table.c.id > last_id).order_by(table.c.id).limit(500)
        if not records:
            query = query.where(table.c.artifact_type == "execution_summary")
        rows = bind.execute(query).all()
        if not rows:
            return
        payloads = []
        for record_id, raw, is_success in rows:
            normalized = _normalize(raw)
            new_success = 0 if records and is_success != 0 and _legacy_failure(normalized) else is_success
            if normalized == raw and new_success == is_success:
                continue
            payload = {"record_id": record_id, "document": normalized}
            if records:
                payload["is_success"] = new_success
            payloads.append(payload)
        if payloads:
            values: dict[str, object] = {column_name: sa.bindparam("document")}
            if records:
                values["is_success"] = sa.bindparam("is_success")
            bind.execute(
                table.update().where(table.c.id == sa.bindparam("record_id")).values(values),
                payloads,
            )
        last_id = rows[-1].id


def upgrade() -> None:
    """补齐状态和错误，纠正旧成功标记，保留原始证据字段。"""
    _migrate("executerecord", "raw_result", records=True)
    _migrate("execution_artifact", "content", records=False)


def downgrade() -> None:
    """不删除补齐字段，以免覆盖升级后产生的真实结果。"""

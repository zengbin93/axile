"""0013 历史执行错误说明的冻结修补与精确恢复。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import groupby
from typing import Any

import sqlalchemy as sa

_TECHNICAL = re.compile(r"(^-?\d+$|\b[\w.]+(?:Error|Exception)\b|Traceback|ErrorID=|return_code=)")
PUBLIC_CODES = {
    "TQ": {
        "CLOSED": "非交易时段",
        "CALENDAR_UNAVAILABLE": "交易日历不可用",
        "QUOTE_TRADING_TIME_UNAVAILABLE": "无法获取品种交易时段",
    },
    "CTP": {
        "CTP.SESSION.CLOSED": "当前不在交易时段",
        "CTP.SESSION.NO_METADATA": "合约资料不可用，交易时段尚未确认",
        "CTP.SESSION.NO_SESSION_TABLE": "未配置合约交易时段",
        "CTP.SESSION.CALENDAR_UNAVAILABLE": "交易日历不可用，交易时段尚未确认",
        "3": "CTP 登录校验失败",
        "31": "资金不足",
    },
    "GM": {"gm_authentication_error": "GM token 无效或已失效", "1000": "GM token 无效或已失效"},
}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _technical(value: object) -> bool:
    text = _text(value)
    return text is not None and bool(
        _TECHNICAL.search(text) or re.fullmatch(r"[A-Z][A-Z0-9_.]*", text) or text == "gm_authentication_error"
    )


def _json(value: object) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _channel(*documents: object) -> str | None:
    found: set[str] = set()
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        extra = document.get("extra")
        for value in (
            document.get("channel_type"),
            document.get("channel"),
            extra.get("channel_type") if isinstance(extra, Mapping) else None,
        ):
            if isinstance(value, str) and value.strip():
                found.add(value.strip().upper())
    return found.pop() if len(found) == 1 else None


def _code(document: Mapping[str, Any], mappings: Mapping[str, Mapping[str, str]]) -> str | None:
    error = _text(document.get("error"))
    found: set[str] = set()
    if error is not None and error in set().union(*[set(items) for items in mappings.values()]):
        found.add(error)
    for key in ("reason_code", "native_code", "error_code", "ErrorID", "status_code", "code"):
        value = document.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            found.add(str(value))
    if document.get("error_type") == "gm_authentication_error":
        found.add("gm_authentication_error")
    return found.pop() if len(found) == 1 else None


def _message(
    document: Mapping[str, Any], channels: tuple[object, ...], mappings: Mapping[str, Mapping[str, str]]
) -> tuple[str | None, str | None]:
    error = _text(document.get("error"))
    code = _code(document, mappings)
    if "error" in document and document["error"] is not None and not isinstance(document["error"], str):
        return None, None
    if error and not _technical(error):
        return None, None
    reason = _text(document.get("outcome_reason"))
    if reason and not _technical(reason) and reason != error:
        return (reason, "outcome_reason") if mappings is PUBLIC_CODES else (None, None)
    channel = _channel(*channels, document)
    if channel and code and code in mappings.get(channel, {}):
        # GM 1000 only has meaning when an explicit authentication context exists.
        if (
            channel == "GM"
            and code == "1000"
            and document.get("operation") not in {"authenticate", "authentication", "login"}
        ):
            return None, None
        if (
            channel == "CTP"
            and code in {"3", "31"}
            and document.get("error_type") not in {"CtpRequestError", "ctp_request_error"}
        ):
            return None, None
        if channel == "TQ" and document.get("operation") not in {"trading_time", "trading_time_check", "session_check"}:
            return None, None
        return mappings[channel][code], f"{channel}:{code}"
    return None, None


@dataclass(frozen=True)
class Change:
    """一个 JSON 路径上的可逆字段修改。"""

    path: tuple[str | int, ...]
    before_present: bool
    before: object
    after_present: bool
    after: object
    rule: str


def _patch_document(
    document: object, channels: tuple[object, ...], mappings: Mapping[str, Mapping[str, str]]
) -> tuple[object, list[Change]]:
    if not isinstance(document, dict):
        return document, []
    copy = json.loads(json.dumps(document))
    changes: list[Change] = []

    def visit(item: object, path: tuple[str | int, ...]) -> None:
        if not isinstance(item, dict):
            return
        error = _text(item.get("error"))
        message, rule = _message(item, (*channels, document), mappings)
        if message is not None and (error is None or _technical(error) or rule is not None):
            if error is not None and "technical_detail" not in item:
                item["technical_detail"] = error
                changes.append(Change(path + ("technical_detail",), False, None, True, error, "technical_detail"))
            changes.append(
                Change(path + ("error",), "error" in item, item.get("error"), True, message, rule or "message")
            )
            item["error"] = message
        symbols = item.get("symbol_results")
        if isinstance(symbols, dict):
            for symbol, value in symbols.items():
                visit(value, path + ("symbol_results", str(symbol)))

    visit(copy, ())
    reconciliation = copy.get("reconciliation")
    rows = reconciliation.get("symbols") if isinstance(reconciliation, dict) else None
    if isinstance(rows, list):
        for change in list(changes):
            if len(change.path) != 3 or change.path[0] != "symbol_results" or change.path[-1] != "error":
                continue
            for index, row in enumerate(rows):
                if (
                    isinstance(row, dict)
                    and row.get("symbol") == change.path[1]
                    and "error" in row
                    and change.before_present
                    and row["error"] == change.before
                ):
                    changes.append(
                        Change(
                            ("reconciliation", "symbols", index, "error"),
                            True,
                            row["error"],
                            True,
                            change.after,
                            change.rule,
                        )
                    )
                    row["error"] = change.after
    return copy, changes


def _path_get(value: dict[str, Any], path: tuple[str | int, ...]) -> tuple[bool, object]:
    current: Any = value
    for part in path:
        if isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
            current = current[part]
            continue
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _path_set(value: dict[str, Any], path: tuple[str | int, ...], present: bool, replacement: object) -> None:
    current: Any = value
    for part in path[:-1]:
        current = current[part]
    if present:
        current[path[-1]] = replacement
    else:
        current.pop(path[-1], None)


def _batches(connection, table, predicate):
    last_id = -1
    while True:
        rows = (
            connection.execute(sa.select(table).where(predicate, table.c.id > last_id).order_by(table.c.id).limit(500))
            .mappings()
            .all()
        )
        if not rows:
            return
        yield from rows
        last_id = rows[-1]["id"]


def _evidence(connection, records, artifacts, events, execution_id):
    if execution_id is None:
        return ()
    inputs = [
        _json(row[0])
        for row in connection.execute(sa.select(records.c.raw_input).where(records.c.execution_id == execution_id))
    ]
    inputs.extend(
        _json(row[0])
        for row in connection.execute(sa.select(records.c.raw_result).where(records.c.execution_id == execution_id))
    )
    inputs.extend(
        _json(row[0])
        for row in connection.execute(
            sa.select(artifacts.c.content).where(
                artifacts.c.execution_id == execution_id,
                artifacts.c.artifact_type.in_(["STANDARD_INPUT", "EXECUTION_SUMMARY"]),
            )
        )
    )
    inputs.extend(
        {"channel": row[0]}
        for row in connection.execute(
            sa.select(events.c.channel).where(events.c.execution_id == execution_id).distinct()
        )
    )
    return tuple(inputs)


def _invalidate(connection, execution_id):
    connection.execute(
        sa.text("""INSERT INTO account_analysis (account_id, source_version)
        SELECT DISTINCT account_id, 1 FROM execution_event WHERE execution_id = :execution_id
        AND account_id IN (SELECT id FROM account)
        UNION SELECT account_id, 1 FROM executerecord WHERE execution_id = :execution_id
        AND account_id IN (SELECT id FROM account)
        ON CONFLICT(account_id) DO UPDATE SET source_version = source_version + 1,
        requested = CASE WHEN failures > 0 OR current_snapshot IS NOT NULL OR running_version IS NOT NULL
        THEN 1 ELSE requested END, failures = 0, retry_at = 0, error = NULL"""),
        {"execution_id": execution_id},
    )


def apply(
    connection: sa.Connection,
    backup_name: str,
    mappings: Mapping[str, Mapping[str, str]],
    *,
    dry_run: bool = False,
    report: dict[str, int] | None = None,
) -> int:
    """修补允许的 JSON 字段，并为每个实际字段改动记录可逆备份。"""
    metadata = sa.MetaData()
    records = sa.Table("executerecord", metadata, autoload_with=connection)
    artifacts = sa.Table("execution_artifact", metadata, autoload_with=connection)
    events = sa.Table("execution_event", metadata, autoload_with=connection)
    backup = sa.Table(
        backup_name,
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_name", sa.Text, nullable=False),
        sa.Column("row_id", sa.Text, nullable=False),
        sa.Column("json_column", sa.Text, nullable=False),
        sa.Column("path", sa.JSON, nullable=False),
        sa.Column("before_present", sa.Boolean, nullable=False),
        sa.Column("before_value", sa.JSON),
        sa.Column("after_present", sa.Boolean, nullable=False),
        sa.Column("after_value", sa.JSON),
        sa.Column("rule", sa.Text, nullable=False),
        sa.Column("identity", sa.JSON, nullable=False),
    )
    if not dry_run:
        backup.create(connection)
    count = 0
    for table, column, predicate in (
        (records, "raw_result", sa.true()),
        (artifacts, "content", artifacts.c.artifact_type == "EXECUTION_SUMMARY"),
    ):
        for row in _batches(connection, table, predicate):
            original = _json(row[column])
            if report is not None:
                report["scanned_rows"] = report.get("scanned_rows", 0) + 1
            patched, changes = _patch_document(
                original,
                (_json(row.get("raw_input")), *_evidence(connection, records, artifacts, events, row["execution_id"])),
                mappings,
            )
            if not changes:
                if report is not None:
                    key = "invalid_shape_rows" if not isinstance(original, dict) else "unchanged_rows"
                    report[key] = report.get(key, 0) + 1
                continue
            count += len(changes)
            if dry_run:
                continue
            key = str(row["id"])
            for change in changes:
                connection.execute(
                    backup.insert().values(
                        table_name=table.name,
                        row_id=key,
                        json_column=column,
                        path=list(change.path),
                        before_present=change.before_present,
                        before_value=change.before,
                        after_present=change.after_present,
                        after_value=change.after,
                        rule=change.rule,
                        identity={
                            key: row[key]
                            for key in ("execution_id", "created_at", "account_id", "artifact_type")
                            if key in row
                        },
                    )
                )
            connection.execute(table.update().where(table.c.id == row["id"]).values({column: patched}))
            if table.name == "execution_artifact":
                _invalidate(connection, row["execution_id"])
    return count


def restore(connection: sa.Connection, backup_name: str, *, dry_run: bool = False) -> None:
    """仅在升级后的字段未被外部改写时精确恢复。"""
    inspector = sa.inspect(connection)
    if backup_name not in inspector.get_table_names():
        raise RuntimeError(f"migration backup missing: {backup_name}")
    metadata = sa.MetaData()
    backup = sa.Table(backup_name, metadata, autoload_with=connection)
    rows = (
        connection.execute(
            sa.select(backup).order_by(backup.c.table_name, backup.c.row_id, backup.c.json_column, backup.c.id)
        )
        .yield_per(500)
        .mappings()
    )
    for (table_name, row_id, column), group in groupby(
        rows, key=lambda row: (row["table_name"], row["row_id"], row["json_column"])
    ):
        changes = list(group)
        table = sa.Table(table_name, metadata, autoload_with=connection)
        row = connection.execute(sa.select(table).where(table.c.id == row_id)).mappings().first()
        if row is None or any(row.get(key) != value for key, value in changes[0]["identity"].items()):
            raise RuntimeError(f"migration restore conflict: {table_name}:{row_id}")
        document = _json(row[column])
        if not isinstance(document, dict):
            raise RuntimeError(f"migration restore conflict: {table_name}:{row_id}")
        for change in changes:
            if _path_get(document, tuple(change["path"])) != (change["after_present"], change["after_value"]):
                raise RuntimeError(f"migration restore conflict: {table_name}:{row_id}:{json.dumps(change['path'])}")
        if dry_run:
            continue
        for change in reversed(changes):
            _path_set(document, tuple(change["path"]), change["before_present"], change["before_value"])
        connection.execute(table.update().where(table.c.id == row_id).values({column: document}))
        if table_name == "execution_artifact":
            _invalidate(connection, row["execution_id"])
    if not dry_run:
        backup.drop(connection)

"""在 SQLite 上验证执行结果数据迁移的原文保留与幂等性。"""

import importlib
import json

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_normalize_execution_errors_preserves_evidence_and_schema(tmp_path):
    migration = importlib.import_module("axile.server.alembic.versions.0013_normalize_execution_result_fields")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'records.db'}")
    originals = [
        {"error": "  原始错误\n", "msg": "备用", "memory": {"message": "更旧"}},
        {"msg": "旧消息", "status": "BLOCKED"},
        {"memory": {"message": "旧内存", "orders": [1]}, "symbol_results": {"A": {"status": "FAILED"}}},
        {"error": "", "msg": "", "memory": {"message": ""}},
        {},
        [],
        None,
        {"error": 5},
        {"msg": " "},
    ] + [{"msg": f"记录 {i}"} for i in range(1001)]
    with engine.begin() as bind:
        bind.exec_driver_sql(
            "CREATE TABLE executerecord (id INTEGER PRIMARY KEY, raw_result JSON, is_success INTEGER NOT NULL DEFAULT 1)"
        )
        bind.exec_driver_sql(
            "CREATE TABLE execution_artifact (id INTEGER PRIMARY KEY, artifact_type TEXT, content JSON)"
        )
        for index, raw in enumerate(originals):
            bind.exec_driver_sql(
                "INSERT INTO executerecord (id, raw_result) VALUES (?, ?)",
                (index, json.dumps(raw, ensure_ascii=False)),
            )
        schema = bind.exec_driver_sql("SELECT sql FROM sqlite_master ORDER BY name").all()
        before = bind.exec_driver_sql("SELECT id, raw_result FROM executerecord ORDER BY id").all()
        batch_sizes = []

        def track_batch(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE"):
                batch_sizes.append(len(parameters) if executemany else 1)

        sa.event.listen(bind, "before_cursor_execute", track_batch)
        with Operations.context(MigrationContext.configure(bind)):
            migration.upgrade()
        assert sum(batch_sizes) == 1004
        assert all(0 < size <= 500 for size in batch_sizes)
        sa.event.remove(bind, "before_cursor_execute", track_batch)
        after = bind.exec_driver_sql("SELECT id, raw_result FROM executerecord ORDER BY id").all()
        for (index, original), (_, changed) in zip(before, after, strict=True):
            raw = originals[index]
            expected = dict(raw) if isinstance(raw, dict) else raw
            candidate = None
            if isinstance(raw, dict) and not (isinstance(raw.get("error"), str) and raw["error"]):
                for value in (
                    raw.get("msg"),
                    raw.get("memory", {}).get("message") if isinstance(raw.get("memory"), dict) else None,
                ):
                    if isinstance(value, str) and value:
                        candidate = value
                        break
            if candidate is None:
                assert changed == original
            else:
                expected["error"] = candidate
            assert json.loads(changed) == expected
        updates = []

        def track_update(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE"):
                updates.append(statement)

        sa.event.listen(bind, "before_cursor_execute", track_update)
        with Operations.context(MigrationContext.configure(bind)):
            migration.upgrade()
            migration.downgrade()
        assert not updates
        assert bind.exec_driver_sql("SELECT id, raw_result FROM executerecord ORDER BY id").all() == after
        assert bind.exec_driver_sql("SELECT sql FROM sqlite_master ORDER BY name").all() == schema


def test_normalize_repairs_legacy_success_conflicts(tmp_path):
    migration = importlib.import_module("axile.server.alembic.versions.0013_normalize_execution_result_fields")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'conflicts.db'}")
    blocked = {"status": "NOOP", "outcome": "blocked", "success": True, "outcome_reason": "无内在价值"}
    cases = [
        ({**blocked, "symbol_results": {"A": blocked}}, "BLOCKED", 0),
        ({"status": "SUCCEEDED", "outcome": "not_reached", "symbol_results": {"A": blocked}}, "PARTIAL", 0),
        ({"status": "SUCCEEDED", "outcome": "error", "error": "拒单"}, "FAILED", 0),
        ({"status": "NOOP", "outcome": "completed", "success": True}, "NOOP", 1),
        ({"status": "SUCCEEDED", "outcome": "unknown", "success": True}, "SUCCEEDED", 1),
        ({"status": "PARTIAL", "outcome": "error", "error": "保留现有失败"}, "PARTIAL", 0),
        ({"status": "NOOP", "success": True}, "NOOP", 1),
        ({"status": "BLOCKED", "outcome": "blocked", "success": True}, "BLOCKED", 0),
    ]
    with engine.begin() as bind:
        bind.exec_driver_sql("CREATE TABLE executerecord (id INTEGER PRIMARY KEY, raw_result JSON, is_success INTEGER)")
        bind.exec_driver_sql(
            "CREATE TABLE execution_artifact (id INTEGER PRIMARY KEY, artifact_type TEXT, content JSON)"
        )
        for index, (raw, _, expected_success) in enumerate(cases):
            bind.exec_driver_sql(
                "INSERT INTO executerecord VALUES (?, ?, ?)",
                (
                    index,
                    json.dumps(raw),
                    1 if raw["status"] in ("NOOP", "SUCCEEDED") or raw.get("success") else expected_success,
                ),
            )
        summary = {**blocked, "reconciliation": {"symbols": [{"symbol": "A", **blocked}]}}
        del summary["status"]
        for index in range(501):
            bind.exec_driver_sql(
                "INSERT INTO execution_artifact VALUES (?, ?, ?)", (index, "execution_summary", json.dumps(summary))
            )
        bind.exec_driver_sql(
            "INSERT INTO execution_artifact VALUES (?, ?, ?)", (501, "account_snapshot", json.dumps(summary))
        )
        with Operations.context(MigrationContext.configure(bind)):
            migration.upgrade()
        rows = bind.exec_driver_sql("SELECT raw_result, is_success FROM executerecord ORDER BY id").all()
        for (original, expected_status, expected_success), (raw, is_success) in zip(cases, rows, strict=True):
            doc = json.loads(raw)
            assert doc["status"] == expected_status
            assert is_success == expected_success
            assert doc.get("outcome") == original.get("outcome")
            if "symbol_results" in doc:
                assert doc["symbol_results"]["A"] == {
                    **blocked,
                    "status": "BLOCKED",
                    "success": False,
                    "error": "无内在价值",
                }
        summaries = bind.exec_driver_sql("SELECT content FROM execution_artifact ORDER BY id").all()
        for (raw,) in summaries[:501]:
            doc = json.loads(raw)
            assert doc["status"] == "BLOCKED"
            assert doc["success"] is False
            assert doc["reconciliation"]["symbols"][0]["status"] == "BLOCKED"
        assert json.loads(summaries[-1][0]) == summary
        updates = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("UPDATE"):
                updates.append(statement)

        sa.event.listen(bind, "before_cursor_execute", capture)
        with Operations.context(MigrationContext.configure(bind)):
            migration.upgrade()
            migration.downgrade()
        assert not updates


def test_outcome_migration_upgrades_records_and_summaries(tmp_path):
    migration = importlib.import_module("axile.server.alembic.versions.0013_normalize_execution_result_fields")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'outcomes.db'}")
    cases = [
        ({"outcome": "error", "error": "旧异常"}, {"status": "FAILED"}),
        ({"outcome": "blocked", "outcome_reason": "休市"}, {"status": "BLOCKED", "error": "休市"}),
        ({"outcome": "error", "msg": "旧消息", "outcome_reason": "备用"}, {"status": "FAILED", "error": "旧消息"}),
        ({"outcome": "error", "memory": {"message": "旧内存"}}, {"status": "FAILED", "error": "旧内存"}),
        ({"outcome": "not_reached"}, {"status": "PARTIAL"}),
        ({"outcome": "completed"}, {"status": "SUCCEEDED"}),
        ({"outcome": "terminated"}, {"task_status": "TERMINATED"}),
        ({"outcome": "completed", "status": "NOOP"}, {}),
        ({"outcome": "error", "status": "PARTIAL", "error": "现有原因", "outcome_reason": "旧原因"}, {}),
        ({"error": "无法据此推断状态"}, {}),
        ({"outcome": "unknown"}, {}),
        ({}, {}),
    ]
    nested = {"outcome": "blocked", "outcome_reason": "交易时段关闭"}
    raw = {"symbol_results": {"A": nested}, "reconciliation": {"symbols": [{"symbol": "A", **nested}]}}
    expected = {"status": "BLOCKED", "error": "交易时段关闭", **nested}
    with engine.begin() as bind:
        bind.exec_driver_sql(
            "CREATE TABLE executerecord (id INTEGER PRIMARY KEY, raw_result JSON, is_success INTEGER NOT NULL DEFAULT 1)"
        )
        bind.exec_driver_sql(
            "CREATE TABLE execution_artifact (id INTEGER PRIMARY KEY, artifact_type TEXT, content JSON)"
        )
        for index, (original, _) in enumerate(cases):
            bind.exec_driver_sql(
                "INSERT INTO executerecord (id, raw_result) VALUES (?, ?)", (index, json.dumps(original))
            )
        # 跨越分页边界，并在摘要和非摘要附件中使用同一证据。
        for index in range(501):
            bind.exec_driver_sql(
                "INSERT INTO execution_artifact VALUES (?, ?, ?)", (index, "execution_summary", json.dumps(raw))
            )
        bind.exec_driver_sql(
            "INSERT INTO execution_artifact VALUES (?, ?, ?)", (501, "account_snapshot", json.dumps(raw))
        )
        with Operations.context(MigrationContext.configure(bind)):
            migration.upgrade()
        rows = bind.exec_driver_sql("SELECT raw_result FROM executerecord ORDER BY id").all()
        for (original, added), (actual,) in zip(cases, rows, strict=True):
            assert json.loads(actual) == {**original, **added}
        summaries = bind.exec_driver_sql("SELECT content FROM execution_artifact ORDER BY id").all()
        for (content,) in summaries[:501]:
            doc = json.loads(content)
            assert doc["symbol_results"]["A"] == expected
            assert doc["reconciliation"]["symbols"] == [{"symbol": "A", **expected}]
        assert json.loads(summaries[501][0]) == raw
        updates = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("UPDATE"):
                updates.append(statement)

        sa.event.listen(bind, "before_cursor_execute", capture)
        with Operations.context(MigrationContext.configure(bind)):
            migration.upgrade()
            migration.downgrade()
        assert not updates

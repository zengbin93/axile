"""执行记录查询伸缩性测试。

覆盖 issue #33：

- ``ExecuteRecord`` 需要按账户查询的复合索引；
- 仪表盘的逐账户查询（N+1）需被批量查询取代，查询数不随账户数线性增长；
- 批量版本必须与逐账户版本语义完全一致。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.server.db.models import ExecuteRecord
from axile.server.repositories import (
    get_earliest_execute_records_since,
    get_earliest_execute_records_since_for_accounts,
    get_execute_records_before,
    get_execute_records_before_for_accounts,
    get_recent_execute_records_by_account_id,
    get_recent_execute_records_for_accounts,
)


@asynccontextmanager
async def _session_scope() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def _make_record(account_id: int, total_asset: float, created_at: str, is_success: int = 1) -> ExecuteRecord:
    return ExecuteRecord(
        account_id=account_id,
        raw_input={},
        raw_result={"account_assets": {"total_asset": total_asset}},
        is_success=is_success,
        created_at=created_at,
    )


async def _seed(session: AsyncSession, accounts: int, per_account: int) -> None:
    for account_id in range(1, accounts + 1):
        for index in range(per_account):
            session.add(_make_record(account_id, 100.0 + index, f"2026-07-{index + 1:02d}T09:00:00"))
    await session.commit()


def test_composite_indexes_exist_on_execute_record() -> None:
    """模型必须声明按账户查询所需的复合索引。"""
    index_columns = {tuple(column.name for column in index.columns) for index in ExecuteRecord.__table__.indexes}

    assert ("account_id", "id") in index_columns
    assert ("account_id", "created_at") in index_columns
    assert ("account_id", "is_success", "id") in index_columns


def test_batch_recent_matches_per_account() -> None:
    """批量取记录必须与逐账户版本逐条一致（含每账户各自 limit）。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed(session, accounts=3, per_account=5)

            batched = await get_recent_execute_records_for_accounts(session, [1, 2, 3], limit=3)

            for account_id in (1, 2, 3):
                expected = await get_recent_execute_records_by_account_id(session, account_id, limit=3)
                assert [r.id for r in batched[account_id]] == [r.id for r in expected]
                assert len(batched[account_id]) == 3, "每个账户各自取 limit 条，而非全局 limit 条"

    asyncio.run(scenario())


def test_batch_recent_handles_missing_and_empty() -> None:
    """无记录的账户不出现在结果中；空账户列表返回空字典。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed(session, accounts=1, per_account=2)

            batched = await get_recent_execute_records_for_accounts(session, [1, 99], limit=5)

            assert 1 in batched
            assert 99 not in batched
            assert await get_recent_execute_records_for_accounts(session, [], limit=5) == {}

    asyncio.run(scenario())


def test_batch_baselines_match_per_account() -> None:
    """今日基准（昨收/今开）的批量版本必须与逐账户版本一致。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed(session, accounts=2, per_account=6)
            boundary = "2026-07-04T00:00:00"

            before = await get_execute_records_before_for_accounts(session, [1, 2], boundary, limit=5)
            since = await get_earliest_execute_records_since_for_accounts(session, [1, 2], boundary, limit=5)

            for account_id in (1, 2):
                expected_before = await get_execute_records_before(session, account_id, boundary, limit=5)
                expected_since = await get_earliest_execute_records_since(session, account_id, boundary, limit=5)
                assert [r.id for r in before.get(account_id, [])] == [r.id for r in expected_before]
                assert [r.id for r in since.get(account_id, [])] == [r.id for r in expected_since]
                assert expected_before, "用例应覆盖到非空的昨收基准"
                assert expected_since, "用例应覆盖到非空的今开基准"

    asyncio.run(scenario())


def test_batch_baselines_empty_account_list() -> None:
    """空账户列表直接返回空字典，不发查询。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            assert await get_execute_records_before_for_accounts(session, [], "2026-07-01T00:00:00") == {}
            assert await get_earliest_execute_records_since_for_accounts(session, [], "2026-07-01T00:00:00") == {}

    asyncio.run(scenario())


def test_batch_query_count_does_not_grow_with_accounts() -> None:
    """核心回归：查询数不随账户数增长（N+1 已消除）。

    逐账户版本对 8 个账户发出 8 条 SQL，批量版本恒为 1 条。
    """

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed(session, accounts=8, per_account=3)
            engine = session.get_bind()

            statements: list[str] = []

            def _record_statement(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
                if "executerecord" in statement.lower():
                    statements.append(statement)

            event.listen(engine, "before_cursor_execute", _record_statement)
            try:
                statements.clear()
                await get_recent_execute_records_for_accounts(session, list(range(1, 9)), limit=3)
                batched_count = len(statements)

                statements.clear()
                for account_id in range(1, 9):
                    await get_recent_execute_records_by_account_id(session, account_id, limit=3)
                per_account_count = len(statements)
            finally:
                event.remove(engine, "before_cursor_execute", _record_statement)

            assert batched_count == 1, f"批量查询应只发一条 SQL，实际 {batched_count} 条"
            assert per_account_count == 8, f"逐账户版本应发 8 条 SQL，实际 {per_account_count} 条"

    asyncio.run(scenario())


def test_account_scoped_query_uses_composite_index() -> None:
    """按账户过滤 + 按 id 排序的查询应命中复合索引，而非全表扫描。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            await _seed(session, accounts=4, per_account=10)

            plan = (
                await session.execute(
                    text("EXPLAIN QUERY PLAN SELECT * FROM executerecord WHERE account_id = 1 ORDER BY id DESC LIMIT 3")
                )
            ).all()
            plan_text = " ".join(str(row) for row in plan)

            assert "ix_executerecord_account_id_id" in plan_text, f"未命中复合索引，执行计划: {plan_text}"
            assert "SCAN executerecord" not in plan_text, f"仍在全表扫描，执行计划: {plan_text}"

    asyncio.run(scenario())

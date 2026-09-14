"""运行态并发测试使用的真实文件库与事务观测器。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from tests.unit.server._execution_test_support import build_account


@asynccontextmanager
async def runtime_database(
    path: Path, *, wal: bool = False
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], list[AsyncSession]]]:
    """提供两个账户及已打开会话，使用真实 BEGIN 暴露读事务升级与锁等待问题。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 0.5})
    sessions: list[AsyncSession] = []

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection: Any, _record: Any) -> None:
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if wal:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    class Session(AsyncSession):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            sessions.append(self)

    factory = async_sessionmaker(engine, class_=Session, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with factory() as session, session.begin():
            session.add_all([build_account(id=1, portfolio_id=None), build_account(id=2, portfolio_id=None)])
        yield factory, sessions
    finally:
        for session in sessions:
            await session.close()
        await engine.dispose()

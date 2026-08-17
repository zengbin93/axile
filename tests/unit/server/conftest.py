"""服务端单元测试共享夹具."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlmodel import SQLModel

# 导入模型包以将全部数据表登记到 ``SQLModel.metadata``
import axile.server.db.models  # noqa: F401
from axile.server.core.db import engine


@pytest.fixture(scope="session", autouse=True)
def _ensure_database_schema() -> Iterator[None]:
    """在服务端单元测试会话开始前，于共享引擎上建好全部表.

    Notes
    -----
    服务端部分用例会经由未被 monkeypatch 的真实 ``SessionLocal`` 触达
    ``axile.server.core.db.engine``。历史上这些用例依赖开发机遗留的
    ``./axile.db`` 文件恰好已含表结构，在全新检出的 CI 环境（无该文件）会
    因 ``no such table`` 失败。此夹具用 ``SQLModel.metadata.create_all``
    幂等建表，消除对遗留文件的隐式依赖；建表后 ``dispose`` 连接池，避免
    连接被绑定到本夹具的事件循环而影响后续按用例创建的事件循环。
    """

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create())
    yield

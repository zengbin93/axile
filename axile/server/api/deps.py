"""Axile API 路由共用的依赖提供器."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import Scheduler, scheduler


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """为当前请求提供数据库会话."""
    async with SessionLocal() as session:
        yield session


def get_scheduler() -> Scheduler:
    """返回应用共用的调度器实例."""
    return scheduler


SessionDep = Annotated[AsyncSession, Depends(get_db)]
SchedDep = Annotated[Scheduler, Depends(get_scheduler)]

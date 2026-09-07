"""Axile API 路由共用的依赖提供器."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends
from pydantic import BaseModel, Field
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


class HistoryPagination(BaseModel):
    """历史列表接口共用的偏移分页参数。"""

    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


HistoryPaginationDep = Annotated[HistoryPagination, Depends()]

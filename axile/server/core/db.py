"""Axile 服务端使用的数据库引擎与异步会话工厂."""

import json

from sqlalchemy import AsyncAdaptedQueuePool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from axile.common.config import settings

engine = create_async_engine(
    str(settings.sqlalchemy_database_uri),
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),  # type: ignore[arg-type]
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

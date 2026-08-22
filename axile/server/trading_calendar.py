"""交易日历的本地查询、上游同步与调度。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import aiohttp
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from axile.common.config import settings
from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import TradingCalendarRecord, now_str

CALENDAR_EXCHANGES = ("SSE", "CFFEX")
CALENDAR_MIN_FUTURE_DAYS = 90
CALENDAR_JOB_ID = "ensure-trading-calendar"
_CALENDAR_TIMEOUT_SECONDS = 10


class TradingCalendarEntry(BaseModel):
    """与胜可知交易日历响应对齐的单日记录。"""

    model_config = ConfigDict(populate_by_name=True)

    exchange: str
    cal_date: date = Field(alias="calDate")
    is_open: bool = Field(alias="isOpen")
    pretrade_date: date | None = Field(default=None, alias="pretradeDate")


_ENTRY_LIST_ADAPTER = TypeAdapter(list[TradingCalendarEntry])


async def list_calendar_entries(
    session: AsyncSession,
    *,
    exchange: str,
    start: date | None = None,
    end: date | None = None,
    only_open: bool = False,
) -> list[TradingCalendarEntry]:
    """从本地数据库按胜可知查询口径读取交易日历。"""
    statement = select(TradingCalendarRecord).where(col(TradingCalendarRecord.exchange) == exchange.upper())
    if start is not None:
        statement = statement.where(col(TradingCalendarRecord.cal_date) >= start)
    if end is not None:
        statement = statement.where(col(TradingCalendarRecord.cal_date) <= end)
    if only_open:
        statement = statement.where(col(TradingCalendarRecord.is_open).is_(True))
    statement = statement.order_by(col(TradingCalendarRecord.cal_date))
    rows = (await session.execute(statement)).scalars().all()
    return [
        TradingCalendarEntry(
            exchange=row.exchange,
            calDate=row.cal_date,
            isOpen=row.is_open,
            pretradeDate=row.pretrade_date,
        )
        for row in rows
    ]


async def _max_calendar_date(session: AsyncSession, exchange: str) -> date | None:
    return await session.scalar(
        select(func.max(col(TradingCalendarRecord.cal_date))).where(col(TradingCalendarRecord.exchange) == exchange)
    )


async def _fetch_calendar(exchange: str) -> list[TradingCalendarEntry]:
    headers = {"Authorization": f"Bearer {settings.trading_calendar_token}"}
    timeout = aiohttp.ClientTimeout(total=_CALENDAR_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.get(
            settings.trading_calendar_api, params={"exchange": exchange}, headers=headers
        ) as response:
            response.raise_for_status()
            payload = await response.json()
    entries = _ENTRY_LIST_ADAPTER.validate_python(payload)
    if not entries:
        raise ValueError(f"{exchange} 交易日历返回空结果")
    if any(entry.exchange.upper() != exchange for entry in entries):
        raise ValueError(f"{exchange} 交易日历响应包含其他交易所")
    return entries


async def _upsert_calendar(session: AsyncSession, entries: list[TradingCalendarEntry]) -> None:
    updated_at = now_str()
    values = [
        {
            "exchange": entry.exchange.upper(),
            "cal_date": entry.cal_date,
            "is_open": entry.is_open,
            "pretrade_date": entry.pretrade_date,
            "updated_at": updated_at,
        }
        for entry in entries
    ]
    statement = sqlite_insert(TradingCalendarRecord).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["exchange", "cal_date"],
        set_={
            "is_open": statement.excluded.is_open,
            "pretrade_date": statement.excluded.pretrade_date,
            "updated_at": statement.excluded.updated_at,
        },
    )
    _ = await session.execute(statement)
    await session.commit()


async def _ensure_exchange(exchange: str, cutoff: date) -> None:
    async with SessionLocal() as session:
        max_date = await _max_calendar_date(session, exchange)
        if max_date is not None and max_date >= cutoff:
            return
    try:
        entries = await _fetch_calendar(exchange)
        async with SessionLocal() as session:
            await _upsert_calendar(session, entries)
        logger.info("已更新 {} 交易日历，共 {} 条", exchange, len(entries))
    except Exception as exc:  # noqa: BLE001 - 后台同步失败不应阻止服务启动
        logger.warning("更新 {} 交易日历失败，保留本地数据: {}", exchange, exc)


async def ensure_trading_calendar_coverage() -> None:
    """在配置上游后，补齐未来不足 90 天的交易日历。"""
    if not settings.trading_calendar_token.strip() or not settings.trading_calendar_api.strip():
        logger.info("未配置交易日历上游，跳过自动同步")
        return
    cutoff = date.today() + timedelta(days=CALENDAR_MIN_FUTURE_DAYS)
    _ = await asyncio.gather(*(_ensure_exchange(exchange, cutoff) for exchange in CALENDAR_EXCHANGES))


def register_trading_calendar_job(scheduler: Scheduler) -> None:
    """注册每月一次的交易日历覆盖检查。"""
    _ = scheduler.add_job(
        ensure_trading_calendar_coverage,
        trigger="cron",
        day=1,
        hour=4,
        minute=0,
        id=CALENDAR_JOB_ID,
        replace_existing=True,
    )


__all__ = [
    "TradingCalendarEntry",
    "ensure_trading_calendar_coverage",
    "list_calendar_entries",
    "register_trading_calendar_job",
]

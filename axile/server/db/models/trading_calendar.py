"""交易日历数据库模型。"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from sqlmodel import Field, SQLModel

from axile.server.db.models.base import now_str


class TradingCalendarRecord(SQLModel, table=True):
    """保存某个日历在单个自然日的基础开闭市状态。"""

    __tablename__: ClassVar[str] = "trading_calendar"

    calendar_id: str = Field(primary_key=True)
    cal_date: date = Field(primary_key=True)
    is_open: bool
    updated_at: str = Field(default_factory=now_str)


class TradingCalendarOverride(SQLModel, table=True):
    """保存人工修正后的单日开闭市状态。"""

    __tablename__: ClassVar[str] = "trading_calendar_override"

    calendar_id: str = Field(primary_key=True)
    cal_date: date = Field(primary_key=True)
    is_open: bool
    updated_at: str = Field(default_factory=now_str)


class TradingCalendarConfig(SQLModel, table=True):
    """保存一份交易日历的刷新方式与健康状态。"""

    __tablename__: ClassVar[str] = "trading_calendar_config"

    calendar_id: str = Field(primary_key=True)
    refresh_kind: str
    function_code: str = ""
    last_sync_at: str | None = None
    updated_at: str = Field(default_factory=now_str)


__all__ = [
    "TradingCalendarOverride",
    "TradingCalendarRecord",
    "TradingCalendarConfig",
]

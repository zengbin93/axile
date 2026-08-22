"""交易日历数据库模型。"""

from __future__ import annotations

from datetime import date

from sqlmodel import Field, SQLModel

from axile.server.db.models.base import now_str


class TradingCalendarRecord(SQLModel, table=True):
    """保存单个交易所某一自然日的开闭市状态。"""

    __tablename__ = "trading_calendar"

    exchange: str = Field(primary_key=True)
    cal_date: date = Field(primary_key=True)
    is_open: bool
    pretrade_date: date | None = None
    updated_at: str = Field(default_factory=now_str)


__all__ = ["TradingCalendarRecord"]

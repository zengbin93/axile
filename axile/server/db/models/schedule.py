"""账户排程跳过记录。"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Literal

from sqlalchemy import Column, ForeignKey, Index, Integer, Text
from sqlmodel import Field, SQLModel

from axile.server.db.models.base import now_str
from axile.server.db.models.execution import ExecuteRecordPublic

type ScheduleSkipReason = Literal["CALENDAR.CLOSED", "CALENDAR.NO_NIGHT_SESSION"]


class ScheduleSkip(SQLModel, table=True):
    """一次因明确休市而跳过的账户排程。"""

    __tablename__: ClassVar[str] = "schedule_skip"
    __table_args__ = (Index("ix_schedule_skip_account_triggered", "account_id", "triggered_at"),)

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    channel: str = Field(sa_column=Column(Text, nullable=False))
    triggered_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))
    calendar_id: str = Field(sa_column=Column(Text, nullable=False))
    calendar_day: date
    calendar_label: str = Field(sa_column=Column(Text, nullable=False))
    reason_code: str = Field(default="CALENDAR.CLOSED", sa_column=Column(Text, nullable=False))


class ExecutionActivity(SQLModel):
    """账户活动流中的执行记录。"""

    kind: Literal["execution"] = "execution"
    occurred_at: str
    record: ExecuteRecordPublic


class ScheduleSkipActivity(SQLModel):
    """账户活动流中的休市跳过记录。"""

    kind: Literal["schedule_skip"] = "schedule_skip"
    occurred_at: str
    id: int
    channel: str
    calendar_id: str
    calendar_day: date
    calendar_label: str
    reason_code: ScheduleSkipReason = "CALENDAR.CLOSED"


class AccountActivityListPublic(SQLModel):
    """按发生时间倒序的账户活动分页。"""

    data: list[ExecutionActivity | ScheduleSkipActivity]
    count: int


__all__ = [
    "AccountActivityListPublic",
    "ExecutionActivity",
    "ScheduleSkip",
    "ScheduleSkipActivity",
]

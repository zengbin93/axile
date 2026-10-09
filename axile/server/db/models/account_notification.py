"""账户通知最近结果与成功的持久化摘要。"""

from typing import ClassVar

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel


class AccountNotificationState(SQLModel, table=True):
    """每账户最多一行；保留最近结果，失败不覆盖最近成功。"""

    __tablename__: ClassVar[str] = "account_notification_state"

    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), primary_key=True))
    last_success_at: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    execution_id: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    last_attempt_event_type: str | None = None
    last_attempt_at: str | None = None
    last_attempt_execution_id: str | None = None
    last_attempt_ok: bool | None = None
    last_attempt_error: str | None = None


class AccountNotificationStatePublic(SQLModel):
    """通知函数最近正常返回的时间和对应执行。"""

    last_success_at: str | None = None
    execution_id: str | None = None
    last_attempt_event_type: str | None = None
    last_attempt_at: str | None = None
    last_attempt_execution_id: str | None = None
    last_attempt_ok: bool | None = None
    last_attempt_error: str | None = None

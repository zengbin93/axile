"""账户最近一次通知成功的持久化摘要。"""

from typing import ClassVar

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel


class AccountNotificationState(SQLModel, table=True):
    """每账户最多一行；失败不会覆盖最近成功。"""

    __tablename__: ClassVar[str] = "account_notification_state"

    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), primary_key=True))
    last_success_at: str = Field(sa_column=Column(Text, nullable=False))
    execution_id: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class AccountNotificationStatePublic(SQLModel):
    """通知函数最近正常返回的时间和对应执行。"""

    last_success_at: str
    execution_id: str | None = None

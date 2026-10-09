"""内部补发组、步骤与持久化通知 outbox，不提供独立 API。"""

from typing import Any, ClassVar

from sqlalchemy import JSON, Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from axile.executor.algorithms.utils.clock import clock_now
from axile.server.db.models.base import new_execution_id


class SupplementGroup(SQLModel, table=True):
    """一次基础排程及其有效补发步骤。"""

    __tablename__: ClassVar[str] = "supplement_group"
    __table_args__ = (UniqueConstraint("account_id", "fingerprint", "base_scheduled_at"),)

    id: str = Field(default_factory=new_execution_id, primary_key=True)
    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    fingerprint: str
    base_scheduled_at: str
    expires_at: str
    configured_count: int
    effective_count: int
    status: str = "active"
    end_reason: str | None = None
    cancel_requested_at: str | None = None


class SupplementStep(SQLModel, table=True):
    """触发与执行的多对一关联，合并 intent 时仍保留所有行。"""

    __tablename__: ClassVar[str] = "supplement_step"
    __table_args__ = (UniqueConstraint("group_id", "index"),)

    id: str = Field(default_factory=new_execution_id, primary_key=True)
    group_id: str = Field(sa_column=Column(Text, ForeignKey("supplement_group.id", ondelete="CASCADE"), nullable=False))
    index: int
    scheduled_at: str
    status: str = "pending"
    execution_id: str | None = Field(default=None, index=True)


class NotificationEvent(SQLModel, table=True):
    """通知派发真源；calling 在重启后变为 unknown，避免重复副作用。"""

    __tablename__: ClassVar[str] = "notification_event"

    sequence: int | None = Field(default=None, primary_key=True)
    id: str = Field(sa_column=Column(Text, unique=True, nullable=False))
    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    created_at: str = Field(default_factory=lambda: clock_now().isoformat())
    event_type: str
    context: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = "pending"
    finished_at: str | None = None
    error: str | None = None

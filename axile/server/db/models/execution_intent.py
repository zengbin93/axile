"""执行意图（intent）持久化模型.

Intent 是执行控制面的真源：一张被接受的调仓/清仓票一行。
``ExecuteRecord`` 仍是结果账，不承担排队与重启恢复。
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Column, ForeignKey, Index, Integer, Text, text
from sqlmodel import Field, SQLModel

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import ExecutionKind, ExecutionTaskStatus, ExecutionTerminateMode
from axile.server.db.models.base import new_execution_id, now_str


class ExecutionIntent(SQLModel, table=True):
    """账户上的一张执行票：排队、在跑或已终态.

    Notes
    -----
    部分唯一索引保证每账户至多一张 ``QUEUED``、至多一张
    ``RUNNING``/``TERMINATING``。终态行可保留对账，历史仍以 ``ExecuteRecord`` 为准。
    """

    __tablename__: ClassVar[str] = "execution_intent"
    __table_args__ = (
        Index("ix_execution_intent_execution_id", "execution_id", unique=True),
        Index("ix_execution_intent_account_id_created_at", "account_id", "created_at"),
        Index(
            "uq_intent_account_queued",
            "account_id",
            unique=True,
            sqlite_where=text("status = 'QUEUED'"),
        ),
        Index(
            "uq_intent_account_running",
            "account_id",
            unique=True,
            sqlite_where=text("status IN ('RUNNING', 'TERMINATING')"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: str = Field(default_factory=new_execution_id, sa_column=Column(Text, nullable=False))
    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    kind: ExecutionKind = Field(sa_column=Column(Text, nullable=False))
    trigger_source: str = Field(sa_column=Column(Text, nullable=False))
    status: ExecutionTaskStatus = Field(sa_column=Column(Text, nullable=False))
    channel: Optional[TradeChannel] = Field(default=None, sa_column=Column(Text, nullable=True))
    algorithm: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON, nullable=False))
    created_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))
    started_at: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    finished_at: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    cancel_requested_at: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    cancel_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    terminate_mode: Optional[ExecutionTerminateMode] = Field(default=None, sa_column=Column(Text, nullable=True))


__all__ = ["ExecutionIntent"]

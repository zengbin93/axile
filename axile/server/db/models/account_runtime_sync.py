"""账户持久化配置到进程运行态的对齐记录。"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from axile.server.db.models.base import now_str


class AccountRuntimeSync(SQLModel, table=True):
    """每个账户一条的运行态对齐目标与最近状态。"""

    __table_args__ = (UniqueConstraint("account_id", name="uq_account_runtime_sync_account"),)

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    status: Literal["pending", "synchronized", "failed"] = Field(
        default="pending", sa_column=Column(Text, nullable=False)
    )
    reset_worker: bool = Field(default=False)
    create_request_key: str | None = Field(default=None, sa_column=Column(Text, nullable=True, unique=True))
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    requested_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))
    last_attempt_at: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    synchronized_at: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class AccountRuntimeSyncAttempt(SQLModel, table=True):
    """运行态对齐的不可变尝试审计记录。"""

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    revision: int = Field(sa_column=Column(Integer, nullable=False))
    succeeded: bool = Field(sa_column_kwargs={"nullable": False})
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    attempted_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))


class AccountRuntimeSyncPublic(SQLModel):
    """客户端可见的运行态同步状态。"""

    status: Literal["pending", "synchronized", "failed"]
    revision: int
    attempts: int
    last_error: str | None = None
    last_attempt_at: str | None = None
    synchronized_at: str | None = None

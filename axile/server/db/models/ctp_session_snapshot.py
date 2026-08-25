"""CTP 品种交易时段本地快照模型。"""

from __future__ import annotations

from typing import ClassVar

from sqlmodel import Field, SQLModel

from axile.server.db.models.base import now_str


class CtpSessionSnapshot(SQLModel, table=True):
    """一份完整的 OpenCTP 品种时段快照及其活动状态。"""

    __tablename__: ClassVar[str] = "ctp_session_snapshot"

    snapshot_id: str = Field(primary_key=True)
    fetched_at: str
    is_active: bool = Field(default=False, index=True)
    created_at: str = Field(default_factory=now_str)


class CtpSessionSnapshotRecord(SQLModel, table=True):
    """属于一份快照的单个品种时段。"""

    __tablename__: ClassVar[str] = "ctp_session_snapshot_record"

    snapshot_id: str = Field(primary_key=True, foreign_key="ctp_session_snapshot.snapshot_id")
    exchange_id: str = Field(primary_key=True)
    product_id: str = Field(primary_key=True)
    segment_no: int = Field(primary_key=True)
    time_begin: str
    time_end: str


__all__ = ["CtpSessionSnapshot", "CtpSessionSnapshotRecord"]

"""目标权重计算快照数据库模型."""

from __future__ import annotations

from typing import Literal, Optional

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Column, ForeignKey, Index, Integer, Text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlmodel import Field, SQLModel

from axile.server.db.models.base import now_str

TargetWeightSnapshotSource = Literal["manual", "execution"]


class TargetWeightSnapshot(AsyncAttrs, SQLModel, table=True):
    """持久化一次成功的组合目标权重计算."""

    __tablename__ = "target_weight_snapshot"
    __table_args__ = (
        Index("ix_target_weight_snapshot_portfolio_id_id", "portfolio_id", "id"),
        Index("ix_target_weight_snapshot_account_id_id", "account_id", "id"),
        Index("ix_target_weight_snapshot_execution_id", "execution_id", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(sa_column=Column(Integer, ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False))
    account_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("account.id", ondelete="SET NULL"), nullable=True),
    )
    raw_weights: Optional[dict[str, float]] = Field(default=None, sa_column=Column(SA_JSON, nullable=True))
    normalized_weights: Optional[dict[str, float]] = Field(default=None, sa_column=Column(SA_JSON, nullable=True))
    source: str = Field(sa_column=Column(Text, nullable=False))
    execution_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    calculated_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))


class TargetWeightSnapshotPublic(SQLModel):
    """页面读取的最近一次目标权重计算结果."""

    weights: dict[str, float] = Field(default_factory=dict)
    quantities: Optional[dict[str, float]] = None
    calculated_at: Optional[str] = None
    source: Optional[TargetWeightSnapshotSource] = None
    execution_id: Optional[str] = None
    context_account_id: Optional[int] = None

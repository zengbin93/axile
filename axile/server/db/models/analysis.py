"""Persistent analysis read models; no execution payloads on the snapshot path."""

import sqlalchemy as sa
from sqlmodel import SQLModel

metadata = SQLModel.metadata
analysis_state = sa.Table(
    "account_analysis",
    metadata,
    sa.Column("account_id", sa.Integer, sa.ForeignKey("account.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("source_version", sa.Integer, nullable=False, server_default="1"),
    sa.Column("published_version", sa.Integer, nullable=False, server_default="0"),
    sa.Column("current_snapshot", sa.Text),
    sa.Column("previous_snapshot", sa.Text),
    sa.Column("requested", sa.Boolean, nullable=False, server_default="0"),
    sa.Column("running_version", sa.Integer),
    sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
    sa.Column("retry_at", sa.Float, nullable=False, server_default="0"),
    sa.Column("error", sa.Text),
    sa.Column("logic_version", sa.Text),
    sa.Column("engine_version", sa.Text),
)
analysis_snapshot = sa.Table(
    "performance_snapshot",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("account_id", sa.Integer, sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("source_version", sa.Integer, nullable=False),
    sa.Column("logic_version", sa.Text, nullable=False),
    sa.Column("engine_version", sa.Text, nullable=False),
    sa.Column("computed_at", sa.Text, nullable=False),
    sa.Column("data_until", sa.Text),
    sa.Column("settings", sa.JSON, nullable=False),
    sa.Column("ranges", sa.JSON, nullable=False),
)
cost_execution = sa.Table(
    "performance_cost_execution",
    metadata,
    sa.Column("snapshot_id", sa.Text, sa.ForeignKey("performance_snapshot.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("record_id", sa.Integer, primary_key=True),
    sa.Column("time", sa.Float, nullable=False),
    sa.Column("success", sa.Boolean, nullable=False),
    sa.Column("noop", sa.Boolean, nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Index("ix_performance_execution_time", "snapshot_id", "time"),
)
cost_trade = sa.Table(
    "performance_cost_trade",
    metadata,
    sa.Column("snapshot_id", sa.Text, sa.ForeignKey("performance_snapshot.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("record_id", sa.Integer, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("time", sa.Float, nullable=False),
    sa.Column("day", sa.Text, nullable=False),
    sa.Column("value", sa.Float),
    sa.Column("cost", sa.Float),
    sa.Column("loss_bp", sa.Float),
    sa.Column("fee", sa.Float),
    sa.Column("fee_currency", sa.Text),
    sa.Column("estimated", sa.Boolean, nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Index("ix_performance_trade_record", "snapshot_id", "record_id", "time"),
    sa.Index("ix_performance_trade_symbol", "snapshot_id", "symbol", "time"),
)

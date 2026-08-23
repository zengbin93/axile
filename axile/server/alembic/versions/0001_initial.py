"""创建 Axile 当前数据库结构的初始基线.

Revision ID: 0001
Revises:
Create Date: 2026-08-17 13:04:05.119307

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 使用的修订标识。
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """从空数据库创建当前完整结构."""
    # ### Alembic 自动生成的命令，请按需调整！ ###
    op.create_table(
        "execution_artifact",
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column(
            "artifact_type",
            sa.Enum(
                "STANDARD_INPUT",
                "TARGET_SNAPSHOT",
                "ACCOUNT_SNAPSHOT",
                "ACCOUNT_SNAPSHOT_BEFORE",
                "TRADE_RULES_SNAPSHOT",
                "MARKET_SNAPSHOT",
                "EXECUTION_SUMMARY",
                name="executionartifacttype",
            ),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "artifact_type", name="uq_execution_artifact_execution_type"),
    )
    op.create_index("ix_execution_artifact_execution", "execution_artifact", ["execution_id"], unique=False)
    op.create_table(
        "portfolio",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("custom_calc_py_code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("tag", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("trade_channel", sa.Text(), nullable=False),
        sa.Column("account_control_preset", sa.Text(), nullable=False),
        sa.Column("account_control_override", sa.JSON(), nullable=True),
        sa.Column("account_config", sa.JSON(), nullable=False),
        sa.Column("is_started", sa.Boolean(), nullable=False),
        sa.Column("cron_expr", sa.Text(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("brokerage", sa.Text(), nullable=False),
        sa.Column("weight_precision", sa.Float(), nullable=False),
        sa.Column("long_leverage", sa.Float(), nullable=True),
        sa.Column("short_leverage", sa.Float(), nullable=True),
        sa.Column("algorithm", sa.JSON(), nullable=True),
        sa.Column("empty_positions_algorithm", sa.JSON(), nullable=True),
        sa.Column("trade_rules", sa.JSON(), nullable=True),
        sa.Column("forbidden_symbols", sa.JSON(), nullable=True),
        sa.Column("risk_symbols", sa.JSON(), nullable=True),
        sa.Column("feishu_key", sa.Text(), nullable=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("write_empty_record", sa.Integer(), nullable=True),
        sa.Column("execution_timeout", sa.Integer(), server_default="180", nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_control_counter_delta",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("control_date", sa.Text(), nullable=False),
        sa.Column("bucket_type", sa.Enum("MINUTE", "DAY", name="accountcontrolbuckettype"), nullable=False),
        sa.Column("bucket_start", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Enum("ACCOUNT", "SYMBOL", name="accountcontrolscopetype"), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("delta_count", sa.Integer(), nullable=False),
        sa.Column("delta_uid", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delta_uid", name="uq_account_control_counter_delta_delta_uid"),
    )
    op.create_index(
        "ix_account_control_counter_delta_account_date",
        "account_control_counter_delta",
        ["account_id", "control_date"],
        unique=False,
    )
    op.create_index(
        "ix_account_control_counter_delta_execution", "account_control_counter_delta", ["execution_id"], unique=False
    )
    op.create_table(
        "account_control_event",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("control_date", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("decision", sa.Enum("ALLOWED", "BLOCKED", name="accountcontroldecision"), nullable=False),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("event_uid", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("occurred_at_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uid", name="uq_account_control_event_event_uid"),
    )
    op.create_index(
        "ix_account_control_event_account_date_created",
        "account_control_event",
        ["account_id", "control_date", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_account_control_event_account_date_symbol_created",
        "account_control_event",
        ["account_id", "control_date", "symbol", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_account_control_event_account_operation_occurred",
        "account_control_event",
        ["account_id", "operation", "occurred_at_ms"],
        unique=False,
    )
    op.create_index(
        "ix_account_control_event_account_symbol_operation_occurred",
        "account_control_event",
        ["account_id", "symbol", "operation", "occurred_at_ms"],
        unique=False,
    )
    op.create_index(
        "ix_account_control_event_execution_seq", "account_control_event", ["execution_id", "seq"], unique=False
    )
    op.create_table(
        "executerecord",
        sa.Column("execution_id", sa.Text(), nullable=True),
        sa.Column("raw_input", sa.JSON(), nullable=False),
        sa.Column("raw_result", sa.JSON(), nullable=False),
        sa.Column("is_success", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executerecord_execution_id", "executerecord", ["execution_id"], unique=True)
    op.create_index(
        "ix_executerecord_account_id_created_at", "executerecord", ["account_id", "created_at"], unique=False
    )
    op.create_index("ix_executerecord_account_id_id", "executerecord", ["account_id", "id"], unique=False)
    op.create_index(
        "ix_executerecord_account_id_success_id", "executerecord", ["account_id", "is_success", "id"], unique=False
    )
    op.create_table(
        "execution_event",
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_uid", sa.Text(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "EXECUTION_STARTED",
                "EXECUTION_TERMINATION_REQUESTED",
                "EXECUTION_TERMINATION_ACKED",
                "EXECUTION_TERMINATED",
                "INPUT_SNAPSHOTTED",
                "TARGET_COMPUTED",
                "SYMBOL_DECISION_MADE",
                "SYMBOL_SKIPPED",
                "ORDER_SUBMITTED",
                "ORDER_ACKNOWLEDGED",
                "ORDER_TERMINAL",
                "EXECUTION_COMPLETED",
                "EXECUTION_FAILED",
                name="executioneventtype",
            ),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Enum("INFO", "SUCCESS", "WARNING", "ERROR", name="executioneventstatus"), nullable=False
        ),
        sa.Column(
            "reason_family",
            sa.Enum(
                "INPUT",
                "RISK",
                "MARKET_RULE",
                "ACCOUNT_STATE",
                "EXECUTION_STRATEGY",
                "EXCHANGE",
                "SYSTEM",
                name="executionreasonfamily",
            ),
            nullable=False,
        ),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("intent_id", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("client_order_id", sa.Text(), nullable=True),
        sa.Column("ts_local_created", sa.Text(), nullable=False),
        sa.Column("ts_exchange", sa.Text(), nullable=True),
        sa.Column("ts_persisted", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uid", name="uq_execution_event_event_uid"),
    )
    op.create_index(
        "ix_execution_event_account_created", "execution_event", ["account_id", "ts_local_created"], unique=False
    )
    op.create_index("ix_execution_event_execution_seq", "execution_event", ["execution_id", "seq"], unique=False)
    op.create_index(
        "ix_execution_event_reason_created", "execution_event", ["reason_code", "ts_local_created"], unique=False
    )
    op.create_index(
        "ix_execution_event_symbol_created", "execution_event", ["symbol", "ts_local_created"], unique=False
    )
    op.create_index(
        "ix_execution_event_type_created", "execution_event", ["event_type", "ts_local_created"], unique=False
    )
    op.create_table(
        "schedule_skip",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("triggered_at", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("calendar_day", sa.Date(), nullable=False),
        sa.Column("calendar_label", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_skip_account_triggered", "schedule_skip", ["account_id", "triggered_at"], unique=False)
    op.create_table(
        "portfolioaccount",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### Alembic 自动生成命令结束 ###


def downgrade() -> None:
    """删除初始基线创建的全部数据库结构."""
    # ### Alembic 自动生成的命令，请按需调整！ ###
    op.drop_table("portfolioaccount")
    op.drop_index("ix_schedule_skip_account_triggered", table_name="schedule_skip")
    op.drop_table("schedule_skip")
    op.drop_index("ix_execution_event_type_created", table_name="execution_event")
    op.drop_index("ix_execution_event_symbol_created", table_name="execution_event")
    op.drop_index("ix_execution_event_reason_created", table_name="execution_event")
    op.drop_index("ix_execution_event_execution_seq", table_name="execution_event")
    op.drop_index("ix_execution_event_account_created", table_name="execution_event")
    op.drop_table("execution_event")
    op.drop_index("ix_executerecord_account_id_success_id", table_name="executerecord")
    op.drop_index("ix_executerecord_account_id_id", table_name="executerecord")
    op.drop_index("ix_executerecord_account_id_created_at", table_name="executerecord")
    op.drop_index("ix_executerecord_execution_id", table_name="executerecord")
    op.drop_table("executerecord")
    op.drop_index("ix_account_control_event_execution_seq", table_name="account_control_event")
    op.drop_index("ix_account_control_event_account_symbol_operation_occurred", table_name="account_control_event")
    op.drop_index("ix_account_control_event_account_operation_occurred", table_name="account_control_event")
    op.drop_index("ix_account_control_event_account_date_symbol_created", table_name="account_control_event")
    op.drop_index("ix_account_control_event_account_date_created", table_name="account_control_event")
    op.drop_table("account_control_event")
    op.drop_index("ix_account_control_counter_delta_execution", table_name="account_control_counter_delta")
    op.drop_index("ix_account_control_counter_delta_account_date", table_name="account_control_counter_delta")
    op.drop_table("account_control_counter_delta")
    op.drop_table("account")
    op.drop_table("portfolio")
    op.drop_index("ix_execution_artifact_execution", table_name="execution_artifact")
    op.drop_table("execution_artifact")
    # ### Alembic 自动生成命令结束 ###

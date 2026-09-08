"""Persist performance batches and transactionally invalidate analysis."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def install_triggers(connection) -> None:
    """Cover ORM, bulk and import writes in the same SQLite transaction."""
    for table in ("executerecord", "portfolioaccount", "target_weight_snapshot", "schedule_skip"):
        for action in ("INSERT", "UPDATE", "DELETE"):
            refs = ("OLD", "NEW") if action == "UPDATE" else ("OLD",) if action == "DELETE" else ("NEW",)
            statements = " ".join(
                f"""INSERT INTO account_analysis (account_id, source_version)
                SELECT {ref}.account_id, 1 WHERE {ref}.account_id IS NOT NULL
                AND EXISTS (SELECT 1 FROM account WHERE id = {ref}.account_id)
                {"AND NEW.account_id IS NOT OLD.account_id" if action == "UPDATE" and ref == "NEW" else ""}
                ON CONFLICT(account_id) DO UPDATE SET source_version = source_version + 1,
                requested = CASE WHEN failures > 0 OR current_snapshot IS NOT NULL OR running_version IS NOT NULL
                THEN 1 ELSE requested END,
                failures = 0, retry_at = 0, error = NULL;"""
                for ref in refs
            )
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS analysis_{table}_{action.lower()} AFTER {action} ON {table} "
                f"BEGIN {statements} END"
            )
    connection.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS analysis_account_settings
        AFTER UPDATE OF backtest_weight_type, backtest_fee_rate ON account
        WHEN OLD.backtest_weight_type IS NOT NEW.backtest_weight_type
        OR OLD.backtest_fee_rate IS NOT NEW.backtest_fee_rate
        BEGIN
        INSERT INTO account_analysis (account_id, source_version) VALUES (NEW.id, 1)
        ON CONFLICT(account_id) DO UPDATE SET source_version = source_version + 1,
        requested = CASE WHEN failures > 0 OR current_snapshot IS NOT NULL OR running_version IS NOT NULL
        THEN 1 ELSE requested END,
        failures = 0, retry_at = 0, error = NULL;
        END""")
    # SQLite deployments do not all enable foreign_keys on every connection.
    connection.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS analysis_account_delete AFTER DELETE ON account
        BEGIN
        DELETE FROM performance_cost_trade WHERE snapshot_id IN (SELECT id FROM performance_snapshot WHERE account_id = OLD.id);
        DELETE FROM performance_cost_execution WHERE snapshot_id IN (SELECT id FROM performance_snapshot WHERE account_id = OLD.id);
        DELETE FROM performance_snapshot WHERE account_id = OLD.id;
        DELETE FROM account_analysis WHERE account_id = OLD.id;
        END""")


def upgrade() -> None:
    """Create immutable result batches and indexed cost projections."""
    op.create_table(
        "account_analysis",
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
    op.create_table(
        "performance_snapshot",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_version", sa.Integer, nullable=False),
        sa.Column("logic_version", sa.Text, nullable=False),
        sa.Column("engine_version", sa.Text, nullable=False),
        sa.Column("computed_at", sa.Text, nullable=False),
        sa.Column("data_until", sa.Text),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("ranges", sa.JSON, nullable=False),
    )
    op.create_index("ix_performance_snapshot_account_id", "performance_snapshot", ["account_id"])
    op.create_table(
        "performance_cost_execution",
        sa.Column(
            "snapshot_id", sa.Text, sa.ForeignKey("performance_snapshot.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("record_id", sa.Integer, primary_key=True),
        sa.Column("time", sa.Float, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("noop", sa.Boolean, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_performance_execution_time", "performance_cost_execution", ["snapshot_id", "time"])
    op.create_table(
        "performance_cost_trade",
        sa.Column(
            "snapshot_id", sa.Text, sa.ForeignKey("performance_snapshot.id", ondelete="CASCADE"), primary_key=True
        ),
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
    )
    op.create_index("ix_performance_trade_record", "performance_cost_trade", ["snapshot_id", "record_id", "time"])
    op.create_index("ix_performance_trade_symbol", "performance_cost_trade", ["snapshot_id", "symbol", "time"])
    install_triggers(op.get_bind())


def downgrade() -> None:
    """Remove derived data without changing execution history."""
    for table in ("executerecord", "portfolioaccount", "target_weight_snapshot", "schedule_skip"):
        for action in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS analysis_{table}_{action}")
    op.execute("DROP TRIGGER IF EXISTS analysis_account_settings")
    op.execute("DROP TRIGGER IF EXISTS analysis_account_delete")
    for table in ("performance_cost_trade", "performance_cost_execution", "performance_snapshot", "account_analysis"):
        op.drop_table(table)

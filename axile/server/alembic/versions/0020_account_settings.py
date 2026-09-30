"""Separate account identity, typed settings, and notification success state."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# Keep the migration independent of evolving application models.
GROUPS = {
    "execution": [
        "account_control_preset",
        "account_control_override",
        "weight_precision",
        "long_leverage",
        "short_leverage",
        "algorithm",
        "empty_positions_algorithm",
        "trade_rules",
        "forbidden_symbols",
        "risk_symbols",
        "write_empty_record",
        "execution_timeout",
    ],
    "schedule": ["is_started", "cron_expr"],
    "notification": ["feishu_key", "execution_notification_code"],
    "backtest": ["backtest_weight_type", "backtest_fee_rate"],
}
JSON_FIELDS = {
    "account_config",
    "account_control_override",
    "algorithm",
    "empty_positions_algorithm",
    "trade_rules",
    "forbidden_symbols",
    "risk_symbols",
}
FLOAT_FIELDS = {"weight_precision", "long_leverage", "short_leverage", "backtest_fee_rate"}
REQUIRED = {
    "account_config",
    "account_control_preset",
    "weight_precision",
    "is_started",
    "cron_expr",
    "execution_timeout",
    "backtest_weight_type",
    "backtest_fee_rate",
}
FIELDS = ["account_config", *(field for fields in GROUPS.values() for field in fields)]


def install_settings_trigger(connection) -> None:
    """Invalidate performance only when its effective backtest settings change."""
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS analysis_account_settings")
    connection.exec_driver_sql("""CREATE TRIGGER analysis_account_settings
        AFTER UPDATE OF backtest ON account_settings
        WHEN json_extract(OLD.backtest, '$.backtest_weight_type') IS NOT json_extract(NEW.backtest, '$.backtest_weight_type')
          OR json_extract(OLD.backtest, '$.backtest_fee_rate') IS NOT json_extract(NEW.backtest, '$.backtest_fee_rate')
        BEGIN
        INSERT INTO account_analysis (account_id, source_version) VALUES (NEW.account_id, 1)
        ON CONFLICT(account_id) DO UPDATE SET source_version = source_version + 1,
        requested = CASE WHEN failures > 0 OR current_snapshot IS NOT NULL OR running_version IS NOT NULL
        THEN 1 ELSE requested END,
        failures = 0, retry_at = 0, error = NULL;
        END""")


def upgrade() -> None:
    """Copy settings before removing legacy account columns."""
    op.create_table(
        "account_settings",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), primary_key=True),
        *(sa.Column(name, sa.JSON(), nullable=False) for name in ["connection", *GROUPS]),
    )
    op.create_table(
        "account_notification_state",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("last_success_at", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=True),
    )
    connection = op.get_bind()
    metadata = sa.MetaData()
    account = sa.Table("account", metadata, autoload_with=connection)
    settings = sa.Table("account_settings", metadata, autoload_with=connection)
    # Stream rows so credentials and potentially large notification sources need not all live in memory.
    for row in connection.execute(sa.select(account)).mappings():
        connection.execute(
            settings.insert().values(
                account_id=row["id"],
                connection=row["account_config"],
                **{group: {field: row[field] for field in fields} for group, fields in GROUPS.items()},
            )
        )
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS analysis_account_settings")
    # Native DROP COLUMN preserves referring rows (SQLite >= 3.35).
    for field in FIELDS:
        op.drop_column("account", field)
    install_settings_trigger(connection)
    connection.exec_driver_sql("""CREATE TRIGGER account_settings_delete AFTER DELETE ON account
        BEGIN
        DELETE FROM account_settings WHERE account_id = OLD.id;
        DELETE FROM account_notification_state WHERE account_id = OLD.id;
        END""")


def downgrade() -> None:
    """Restore the exact flat configuration values before dropping settings."""
    connection = op.get_bind()
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS analysis_account_settings")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS account_settings_delete")
    triggers = list(connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='trigger'").all())
    for name, _sql in triggers:
        connection.exec_driver_sql(f'DROP TRIGGER "{name}"')
    with op.batch_alter_table("account") as batch:
        for field in FIELDS:
            kind = (
                sa.JSON()
                if field in JSON_FIELDS
                else sa.Float()
                if field in FLOAT_FIELDS
                else sa.Boolean()
                if field == "is_started"
                else sa.Integer()
                if field in {"execution_timeout", "write_empty_record"}
                else sa.Text()
            )
            defaults = {"execution_timeout": "180", "backtest_weight_type": "'ts'", "backtest_fee_rate": "0"}
            default = sa.text(defaults[field]) if field in defaults else None
            batch.add_column(sa.Column(field, kind, nullable=True, server_default=default))
    connection = op.get_bind()
    metadata = sa.MetaData()
    account = sa.Table("account", metadata, autoload_with=connection)
    settings = sa.Table("account_settings", metadata, autoload_with=connection)
    for row in connection.execute(sa.select(settings)).mappings():
        values = {"account_config": row["connection"]}
        for group in GROUPS:
            values.update(row[group])
        connection.execute(account.update().where(account.c.id == row["account_id"]).values(**values))
    with op.batch_alter_table("account") as batch:
        for field in REQUIRED:
            batch.alter_column(field, nullable=False)
    for _name, trigger in triggers:
        connection.exec_driver_sql(trigger)
    connection.exec_driver_sql("""CREATE TRIGGER analysis_account_settings
        AFTER UPDATE OF backtest_weight_type, backtest_fee_rate ON account
        WHEN OLD.backtest_weight_type IS NOT NEW.backtest_weight_type OR OLD.backtest_fee_rate IS NOT NEW.backtest_fee_rate
        BEGIN
        INSERT INTO account_analysis (account_id, source_version) VALUES (NEW.id, 1)
        ON CONFLICT(account_id) DO UPDATE SET source_version = source_version + 1,
        requested = CASE WHEN failures > 0 OR current_snapshot IS NOT NULL OR running_version IS NOT NULL
        THEN 1 ELSE requested END,
        failures = 0, retry_at = 0, error = NULL;
        END""")
    op.drop_table("account_notification_state")
    op.drop_table("account_settings")

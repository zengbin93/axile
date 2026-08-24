from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATIONS_DIR = Path(__file__).parents[3] / "axile" / "server" / "alembic" / "versions"


def _load_migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("initial_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def test_migration_history_is_linear() -> None:
    migration_paths = tuple(sorted(_MIGRATIONS_DIR.glob("[0-9]*.py")))

    assert [path.name for path in migration_paths] == [
        "0001_initial.py",
        "0002_trading_calendar.py",
        "0003_plugin_network.py",
        "0004_account_asset_snapshot.py",
    ]
    initial = _load_migration(migration_paths[0])
    calendar = _load_migration(migration_paths[1])
    plugin_network = _load_migration(migration_paths[2])
    account_asset_snapshot = _load_migration(migration_paths[3])
    assert initial.revision == "0001"
    assert initial.down_revision is None
    assert calendar.revision == "0002"
    assert calendar.down_revision == "0001"
    assert plugin_network.revision == "0003"
    assert plugin_network.down_revision == "0002"
    assert account_asset_snapshot.revision == "0004"
    assert account_asset_snapshot.down_revision == "0003"


def test_account_asset_snapshot_migration_backfills_execution_assets() -> None:
    migration = _load_migration(_MIGRATIONS_DIR / "0004_account_asset_snapshot.py")
    engine = sa.create_engine("sqlite://")

    metadata = sa.MetaData()
    sa.Table(
        "account",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    records = sa.Table(
        "executerecord",
        metadata,
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=True),
        sa.Column("raw_result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(sa.text("INSERT INTO account (id) VALUES (1)"))
        connection.execute(
            records.insert(),
            [
                {
                    "account_id": 1,
                    "execution_id": "exec-1",
                    "raw_result": {"account_assets": {"total_asset": 123.0, "positions": []}},
                    "created_at": "2026-08-24T09:30:00",
                },
                {
                    "account_id": 1,
                    "execution_id": "exec-2",
                    "raw_result": {"error": "before snapshot"},
                    "created_at": "2026-08-24T09:31:00",
                },
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        rows = connection.execute(sa.text("SELECT * FROM account_asset_snapshot")).mappings().all()
        assert len(rows) == 1
        assert rows[0]["account_id"] == 1
        assert rows[0]["execution_id"] == "exec-1"
        assert rows[0]["source"] == "execution"


def test_initial_baseline_creates_the_current_schema() -> None:
    migration = _load_migration(_MIGRATIONS_DIR / "0001_initial.py")
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        inspector = sa.inspect(connection)
        assert set(inspector.get_table_names()) == {
            "account",
            "account_control_counter_delta",
            "account_control_event",
            "executerecord",
            "execution_artifact",
            "execution_event",
            "portfolio",
            "portfolioaccount",
            "schedule_skip",
        }

        for table_name, column_name in (
            ("account", "trade_channel"),
            ("execution_event", "channel"),
            ("account_control_event", "channel"),
        ):
            columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert isinstance(columns[column_name]["type"], sa.Text)
            assert columns[column_name]["nullable"] is False

        assert {
            "ix_executerecord_execution_id",
            "ix_executerecord_account_id_id",
            "ix_executerecord_account_id_created_at",
            "ix_executerecord_account_id_success_id",
        } <= _index_names(inspector, "executerecord")
        assert {
            "ix_account_control_event_execution_seq",
            "ix_account_control_event_account_operation_occurred",
            "ix_account_control_event_account_symbol_operation_occurred",
        } <= _index_names(inspector, "account_control_event")

        execute_record_indexes = {index["name"]: index for index in inspector.get_indexes("executerecord")}
        assert execute_record_indexes["ix_executerecord_execution_id"]["unique"] == 1

        account_foreign_keys = inspector.get_foreign_keys("account")
        assert any(
            foreign_key["referred_table"] == "portfolio"
            and foreign_key["constrained_columns"] == ["portfolio_id"]
            and foreign_key["options"].get("ondelete") == "SET NULL"
            for foreign_key in account_foreign_keys
        )

        event_unique_constraints = {
            constraint["name"] for constraint in inspector.get_unique_constraints("execution_event")
        }
        assert "uq_execution_event_event_uid" in event_unique_constraints

        event_type = {column["name"]: column for column in inspector.get_columns("execution_event")}["event_type"][
            "type"
        ]
        assert "SCHEDULE_SKIPPED" not in getattr(event_type, "enums", ())

        schedule_skip_foreign_keys = inspector.get_foreign_keys("schedule_skip")
        assert any(
            foreign_key["referred_table"] == "account"
            and foreign_key["constrained_columns"] == ["account_id"]
            and foreign_key["options"].get("ondelete") == "CASCADE"
            for foreign_key in schedule_skip_foreign_keys
        )
        assert "ix_schedule_skip_account_triggered" in _index_names(inspector, "schedule_skip")

        portfolio_columns = {column["name"]: column for column in inspector.get_columns("portfolio")}
        assert portfolio_columns["custom_calc_py_code"]["nullable"] is False


def test_trading_calendar_migration_adds_calendar_table() -> None:
    initial = _load_migration(_MIGRATIONS_DIR / "0001_initial.py")
    calendar = _load_migration(_MIGRATIONS_DIR / "0002_trading_calendar.py")
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        initial.op = operations
        initial.upgrade()
        calendar.op = operations
        calendar.upgrade()

        inspector = sa.inspect(connection)
        assert {
            "trading_calendar",
            "trading_calendar_override",
            "trading_calendar_config",
        } <= set(inspector.get_table_names())
        assert inspector.get_pk_constraint("trading_calendar")["constrained_columns"] == [
            "calendar_id",
            "cal_date",
        ]
        assert inspector.get_pk_constraint("trading_calendar_override")["constrained_columns"] == [
            "calendar_id",
            "cal_date",
        ]
        assert inspector.get_pk_constraint("trading_calendar_config")["constrained_columns"] == ["calendar_id"]
        config_columns = {column["name"] for column in inspector.get_columns("trading_calendar_config")}
        assert config_columns == {
            "calendar_id",
            "refresh_kind",
            "function_code",
            "last_sync_at",
            "updated_at",
        }


def test_plugin_network_migration_rewrites_account_config_and_downgrades() -> None:
    initial = _load_migration(_MIGRATIONS_DIR / "0001_initial.py")
    migration = _load_migration(_MIGRATIONS_DIR / "0003_plugin_network.py")
    engine = sa.create_engine("sqlite://")
    account = sa.table(
        "account",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.Text()),
        sa.column("market", sa.Text()),
        sa.column("trade_channel", sa.Text()),
        sa.column("account_control_preset", sa.Text()),
        sa.column("account_config", sa.JSON()),
        sa.column("is_started", sa.Boolean()),
        sa.column("cron_expr", sa.Text()),
        sa.column("brokerage", sa.Text()),
        sa.column("weight_precision", sa.Float()),
        sa.column("updated_at", sa.Text()),
        sa.column("created_at", sa.Text()),
    )

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        initial.op = operations
        initial.upgrade()
        common = {
            "name": "account",
            "market": "demo-market",
            "account_control_preset": "default",
            "is_started": False,
            "cron_expr": "",
            "brokerage": "",
            "weight_precision": 0.001,
            "updated_at": "now",
            "created_at": "now",
        }
        connection.execute(
            sa.insert(account),
            [
                {**common, "id": 1, "trade_channel": "plugin-channel", "account_config": {"is_testnet": True}},
                {**common, "id": 2, "trade_channel": "plugin-channel", "account_config": {"is_testnet": False}},
                {
                    **common,
                    "id": 3,
                    "trade_channel": "plugin-channel",
                    "account_config": {"is_testnet": True, "network": "mainnet"},
                },
                {**common, "id": 4, "trade_channel": "gm", "account_config": {"is_testnet": True}},
            ],
        )

        migration.op = operations
        migration.upgrade()
        upgraded = dict(connection.execute(sa.select(account.c.id, account.c.account_config)).all())
        assert upgraded[1] == {"network": "testnet"}
        assert upgraded[2] == {"network": "mainnet"}
        assert upgraded[3] == {"network": "mainnet"}
        assert upgraded[4] == {"is_testnet": True}

        migration.downgrade()
        downgraded = dict(connection.execute(sa.select(account.c.id, account.c.account_config)).all())
        assert downgraded[1] == {"is_testnet": True}
        assert downgraded[2] == {"is_testnet": False}
        assert downgraded[3] == {"is_testnet": False}
        assert downgraded[4] == {"is_testnet": True}

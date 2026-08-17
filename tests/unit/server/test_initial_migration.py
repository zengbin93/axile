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


def test_migration_history_contains_only_the_initial_baseline() -> None:
    migration_paths = tuple(sorted(_MIGRATIONS_DIR.glob("[0-9]*.py")))

    assert [path.name for path in migration_paths] == ["0001_initial.py"]
    migration = _load_migration(migration_paths[0])
    assert migration.revision == "0001"
    assert migration.down_revision is None


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
            "strategyconfig",
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

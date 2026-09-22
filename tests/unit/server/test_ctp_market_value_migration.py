"""Historical CTP valuation migration integration tests."""

import pytest
import sqlalchemy as sa

from axile.server.migration_support.ctp_market_value import downgrade, upgrade


def test_repairs_joined_ctp_observations_and_restores_exact_originals() -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    accounts = sa.Table(
        "account", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("trade_channel", sa.Text)
    )
    records = sa.Table(
        "executerecord",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("execution_id", sa.Text),
        sa.Column("raw_input", sa.JSON),
        sa.Column("raw_result", sa.JSON),
    )
    snapshots = sa.Table(
        "account_asset_snapshot",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("execution_id", sa.Text),
        sa.Column("assets", sa.JSON),
    )
    artifacts = sa.Table(
        "execution_artifact",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("execution_id", sa.Text),
        sa.Column("artifact_type", sa.Text),
        sa.Column("content", sa.JSON),
    )
    assets = {
        "market_value": 33,
        "total_asset": 500,
        "positions": [
            {"symbol": "rb", "volume": 2, "market_value": 33},
            {"symbol": "ag", "volume": 1, "market_value": 0},
        ],
    }
    result = {
        "account_assets": assets,
        "symbol_results": {
            "rb": {"first_tick": {"last_price": 100, "timestamp": 1780000000000}, "sizing": {"unit_multiplier": 10}}
        },
    }
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(accounts.insert(), [{"id": 1, "trade_channel": "ctp"}, {"id": 2, "trade_channel": "gm"}])
        connection.execute(
            records.insert(),
            [
                {"id": 1, "account_id": 1, "execution_id": "ctp-1", "raw_input": {}, "raw_result": result},
                {"id": 2, "account_id": 2, "execution_id": "gm-1", "raw_input": {}, "raw_result": result},
            ],
        )
        connection.execute(
            snapshots.insert(),
            [
                {"id": 1, "account_id": 1, "execution_id": "ctp-1", "assets": assets},
                {"id": 2, "account_id": 2, "execution_id": "gm-1", "assets": assets},
            ],
        )
        connection.execute(
            artifacts.insert(),
            [
                {
                    "id": 1,
                    "execution_id": "ctp-1",
                    "artifact_type": "ACCOUNT_SNAPSHOT",
                    "content": {"account_assets": assets},
                },
                {
                    "id": 3,
                    "execution_id": "ctp-1",
                    "artifact_type": "ACCOUNT_SNAPSHOT_BEFORE",
                    "content": {"account_assets": assets},
                },
                {
                    "id": 2,
                    "execution_id": "gm-1",
                    "artifact_type": "ACCOUNT_SNAPSHOT",
                    "content": {"account_assets": assets},
                },
            ],
        )
        upgrade(connection)
        repaired = connection.scalar(sa.select(snapshots.c.assets).where(snapshots.c.id == 1))
        assert repaired["positions"][0]["market_value"] == 2000
        assert repaired["positions"][1]["market_value"] is None
        assert repaired["market_value"] is None
        assert repaired["positions"][0]["extra"] == {
            "position_cost": 33,
            "market_value_provenance": {
                "source": "ctp_first_tick_last_price_0014",
                "quote_timestamp": 1780000000000,
            },
        }
        assert connection.scalar(sa.select(records.c.raw_result).where(records.c.id == 1))["account_assets"] == repaired
        assert (
            connection.scalar(sa.select(artifacts.c.content).where(artifacts.c.id == 1))["account_assets"] == repaired
        )
        assert (
            connection.scalar(sa.select(artifacts.c.content).where(artifacts.c.id == 3))["account_assets"] == repaired
        )
        assert connection.scalar(sa.select(snapshots.c.assets).where(snapshots.c.id == 2)) == assets
        assert connection.scalar(sa.select(records.c.raw_result).where(records.c.id == 2)) == result
        downgrade(connection)
        assert connection.scalar(sa.select(snapshots.c.assets).where(snapshots.c.id == 1)) == assets
        assert connection.scalar(sa.select(records.c.raw_result).where(records.c.id == 1)) == result
        assert connection.scalar(sa.select(artifacts.c.content).where(artifacts.c.id == 1)) == {
            "account_assets": assets
        }


def test_downgrade_refuses_external_edits() -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    accounts = sa.Table(
        "account", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("trade_channel", sa.Text)
    )
    records = sa.Table(
        "executerecord",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("execution_id", sa.Text),
        sa.Column("raw_input", sa.JSON),
        sa.Column("raw_result", sa.JSON),
    )
    sa.Table(
        "account_asset_snapshot",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("execution_id", sa.Text),
        sa.Column("assets", sa.JSON),
    )
    sa.Table(
        "execution_artifact",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("execution_id", sa.Text),
        sa.Column("artifact_type", sa.Text),
        sa.Column("content", sa.JSON),
    )
    result = {
        "account_assets": {"positions": [{"symbol": "rb", "volume": 1, "market_value": 8}], "market_value": 8},
        "symbol_results": {
            "rb": {"first_tick": {"last_price": 100, "timestamp": 1780000000000}, "sizing": {"unit_multiplier": 10}}
        },
    }
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(accounts.insert().values(id=1, trade_channel="ctp"))
        connection.execute(
            records.insert().values(id=1, account_id=1, execution_id="one", raw_input={}, raw_result=result)
        )
        upgrade(connection)
        changed = connection.scalar(sa.select(records.c.raw_result))
        changed["account_assets"]["total_asset"] = 999
        connection.execute(records.update().values(raw_result=changed))
        with pytest.raises(RuntimeError, match="restore conflict"):
            downgrade(connection)
        assert "axile_0014_market_value_backup" in sa.inspect(connection).get_table_names()

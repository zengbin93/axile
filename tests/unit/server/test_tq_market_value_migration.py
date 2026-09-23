"""TQ historical market value repair tests."""

import pytest
import sqlalchemy as sa

from axile.server.migration_support.tq_market_value import downgrade, upgrade


def test_repair_same_observation_quotes_and_guarded_restore() -> None:
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
        sa.Column("raw_result", sa.JSON),
        sa.Column("created_at", sa.Text),
    )
    snapshots = sa.Table(
        "account_asset_snapshot",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("execution_id", sa.Text),
        sa.Column("assets", sa.JSON),
        sa.Column("created_at", sa.Text),
    )
    artifacts = sa.Table(
        "execution_artifact",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("execution_id", sa.Text),
        sa.Column("artifact_type", sa.Text),
        sa.Column("content", sa.JSON),
        sa.Column("created_at", sa.Text),
    )
    assets = {
        "update_time": "2026-09-22T15:00:00",
        "total_asset": 500,
        "available_cash": 400,
        "market_value": 30,
        "positions": [
            {"symbol": "rb", "volume": 2, "market_value": 20, "extra": {"tq_symbol": "SHFE.rb"}},
            {"symbol": "ag", "volume": 1, "market_value": 10, "extra": {"tq_symbol": "SHFE.ag"}},
        ],
        "extra": {
            "quotes": {
                "SHFE.rb": {
                    "tq_symbol": "SHFE.rb",
                    "last_price": 100,
                    "volume_multiple": 10,
                    "datetime": "2026-09-22T14:59:00",
                },
                "SHFE.ag": {
                    "tq_symbol": "SHFE.ag",
                    "last_price": 200,
                    "volume_multiple": 10,
                    "datetime": "2026-09-22T14:50:00",
                },
            }
        },
    }
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(accounts.insert().values(id=1, trade_channel="tq"))
        connection.execute(
            records.insert().values(
                id=1,
                account_id=1,
                execution_id="e1",
                raw_result={"account_assets": assets},
                created_at=assets["update_time"],
            )
        )
        connection.execute(
            snapshots.insert().values(
                id=1, account_id=1, execution_id="e1", assets=assets, created_at=assets["update_time"]
            )
        )
        connection.execute(
            artifacts.insert().values(
                id=1,
                execution_id="e1",
                artifact_type="ACCOUNT_SNAPSHOT",
                content={"account_assets": assets},
                created_at=assets["update_time"],
            )
        )
        upgrade(connection)
        repaired = connection.scalar(sa.select(snapshots.c.assets))
        assert repaired["positions"][0]["market_value"] == 2000
        assert repaired["positions"][1]["market_value"] is None
        assert repaired["market_value"] is None
        assert repaired["total_asset"] == 500
        assert repaired["available_cash"] == 400
        assert repaired["positions"][1]["extra"]["position_cost"] == 10
        assert connection.scalar(sa.select(records.c.raw_result))["account_assets"] == repaired
        assert connection.scalar(sa.select(artifacts.c.content))["account_assets"] == repaired
        changed = {**repaired, "total_asset": 999}
        connection.execute(snapshots.update().values(assets=changed))
        with pytest.raises(RuntimeError, match="restore conflict"):
            downgrade(connection)
        connection.execute(snapshots.update().values(assets=repaired))
        downgrade(connection)
        assert connection.scalar(sa.select(snapshots.c.assets)) == assets


def test_repair_skips_new_provenance() -> None:
    assets = {
        "positions": [
            {"volume": 1, "market_value": 100, "extra": {"market_value_provenance": {"source": "tq_last_price"}}}
        ]
    }
    from axile.server.migration_support.tq_market_value import _repair

    assert _repair(assets, "2026-09-22T15:00:00") is None

"""Repair legacy TQ cost-basis values using evidence from the same observation."""

from __future__ import annotations

import json
import math
from datetime import datetime

import sqlalchemy as sa

from axile.server.migration_support.ctp_market_value import _document, _pages

PROVENANCE = "tq_historical_last_price_0015"


def _timestamp(value: object) -> float | None:
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            if not math.isfinite(number):
                return None
            if number > 1e17:
                return number / 1e9
            if number > 1e11:
                return number / 1e3
            return number
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (OverflowError, OSError, TypeError, ValueError):
        pass
    return None


def _positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _quote(assets: dict, position: dict, observation_time: object) -> tuple[float, float, object] | None:
    """Accept only an exact-contract quote embedded in this asset observation."""
    extra = assets.get("extra")
    quotes = extra.get("quotes") if isinstance(extra, dict) else None
    symbol = position.get("extra", {}).get("tq_symbol") or position.get("symbol")
    row = quotes.get(symbol) if isinstance(quotes, dict) and isinstance(symbol, str) else None
    if not isinstance(row, dict):
        return None
    row_symbol = row.get("tq_symbol") or row.get("symbol")
    if row_symbol != symbol:
        return None
    price = _positive(row.get("last_price"))
    multiplier = _positive(row.get("volume_multiple"))
    quote_time = row.get("datetime") or row.get("timestamp") or row.get("update_time")
    observed = _timestamp(observation_time)
    quoted = _timestamp(quote_time)
    if price is None or multiplier is None or observed is None or quoted is None:
        return None
    if not 0 <= observed - quoted <= 300:
        return None
    return price, multiplier, quote_time


def _repair(assets: dict, observation_time: object) -> dict | None:
    positions = assets.get("positions")
    if not isinstance(positions, list) or not positions or not all(isinstance(p, dict) for p in positions):
        return None
    if any(not isinstance(p.get("extra", {}), dict) for p in positions):
        return None
    if any("market_value_provenance" in p or "market_value_provenance" in p.get("extra", {}) for p in positions):
        return None
    if not all(
        _positive(p.get("volume")) is not None and isinstance(p.get("market_value"), (int, float)) for p in positions
    ):
        return None
    repaired = json.loads(json.dumps(assets))
    values: list[float] = []
    for position in repaired["positions"]:
        extra = position.setdefault("extra", {})
        extra["position_cost"] = position["market_value"]
        evidence = _quote(repaired, position, observation_time)
        if evidence is None:
            position["market_value"] = None
            extra["market_value_provenance"] = {"source": "unavailable", "reason": "no_same_observation_quote"}
            continue
        price, multiplier, quoted_at = evidence
        value = abs(float(position["volume"])) * price * multiplier
        if not math.isfinite(value):
            position["market_value"] = None
            extra["market_value_provenance"] = {"source": "unavailable", "reason": "calculation_overflow"}
            continue
        position["market_value"] = value
        extra["market_value_provenance"] = {
            "source": PROVENANCE,
            "price": price,
            "multiplier": multiplier,
            "quote_time": quoted_at,
        }
        values.append(value)
    total = sum(values)
    repaired["market_value"] = total if len(values) == len(positions) and math.isfinite(total) else None
    return repaired


def upgrade(connection: sa.Connection) -> None:
    """Repair TQ observations and save exact before and after JSON for rollback."""
    metadata = sa.MetaData()
    accounts = sa.Table("account", metadata, autoload_with=connection)
    snapshots = sa.Table("account_asset_snapshot", metadata, autoload_with=connection)
    records = sa.Table("executerecord", metadata, autoload_with=connection)
    artifacts = sa.Table("execution_artifact", metadata, autoload_with=connection)
    backup = sa.Table(
        "axile_0015_tq_market_value_backup",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_name", sa.Text, nullable=False),
        sa.Column("row_id", sa.Integer, nullable=False),
        sa.Column("json_column", sa.Text, nullable=False),
        sa.Column("before", sa.JSON, nullable=False),
        sa.Column("after", sa.JSON, nullable=False),
        sa.Column("execution_id", sa.Text),
    )
    backup.create(connection)
    tq_accounts = set(connection.scalars(sa.select(accounts.c.id).where(accounts.c.trade_channel == "tq")))
    execution_accounts: dict[str, int] = {}
    for row in _pages(connection, sa.select(records), records.c.id):
        if row["account_id"] in tq_accounts and row["execution_id"]:
            execution_accounts[row["execution_id"]] = row["account_id"]
    targets = (
        (snapshots, "assets", "account_id"),
        (records, "raw_result", "account_id"),
        (artifacts, "content", None),
    )
    for table, column, account_column in targets:
        for row in _pages(connection, sa.select(table), table.c.id):
            account_id = row[account_column] if account_column else execution_accounts.get(row["execution_id"])
            if account_id not in tq_accounts:
                continue
            if table is artifacts and row["artifact_type"] not in ("ACCOUNT_SNAPSHOT", "ACCOUNT_SNAPSHOT_BEFORE"):
                continue
            document = _document(row[column])
            if document is None:
                continue
            assets = document if table is snapshots else document.get("account_assets")
            if not isinstance(assets, dict):
                continue
            observed = assets.get("update_time") or row.get("created_at")
            repaired = _repair(assets, observed)
            if repaired is None:
                continue
            after = repaired if table is snapshots else {**document, "account_assets": repaired}
            connection.execute(
                backup.insert().values(
                    table_name=table.name,
                    row_id=row["id"],
                    json_column=column,
                    before=document,
                    after=after,
                    execution_id=row["execution_id"],
                )
            )
            connection.execute(table.update().where(table.c.id == row["id"]).values({column: after}))


def downgrade(connection: sa.Connection) -> None:
    """Restore only documents unchanged since migration."""
    metadata = sa.MetaData()
    backup = sa.Table("axile_0015_tq_market_value_backup", metadata, autoload_with=connection)
    tables = {
        name: sa.Table(name, metadata, autoload_with=connection)
        for name in ("account_asset_snapshot", "executerecord", "execution_artifact")
    }
    entries = list(_pages(connection, sa.select(backup), backup.c.id))
    for entry in entries:
        table = tables[entry["table_name"]]
        row = connection.execute(sa.select(table).where(table.c.id == entry["row_id"])).mappings().first()
        if (
            row is None
            or row["execution_id"] != entry["execution_id"]
            or _document(row[entry["json_column"]]) != entry["after"]
        ):
            raise RuntimeError(f"0015 restore conflict: {entry['table_name']}:{entry['row_id']}")
    for entry in entries:
        table = tables[entry["table_name"]]
        connection.execute(
            table.update().where(table.c.id == entry["row_id"]).values({entry["json_column"]: entry["before"]})
        )
    backup.drop(connection)

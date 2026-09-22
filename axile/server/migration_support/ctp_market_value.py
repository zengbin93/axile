"""0014 CTP historical position-cost valuation repair."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

import sqlalchemy as sa

PROVENANCE = "ctp_first_tick_last_price_0014"


def _number(value: object) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


def _document(value: object) -> dict | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _quotes(result: Mapping) -> dict[str, tuple[float, float, object]]:
    quotes = {}
    symbols = result.get("symbol_results")
    if not isinstance(symbols, dict):
        return quotes
    for symbol, item in symbols.items():
        if not isinstance(item, dict):
            continue
        tick, sizing = item.get("first_tick"), item.get("sizing")
        if not isinstance(tick, dict) or not isinstance(sizing, dict):
            continue
        price = _number(tick.get("last_price"))
        multiplier = _number(sizing.get("unit_multiplier"))
        if price is not None and price > 0 and multiplier is not None and multiplier > 0:
            quotes[symbol] = (price, multiplier, tick.get("timestamp") or tick.get("update_time"))
    return quotes


def _repair(assets: dict, quotes: dict[str, tuple[float, float, object]]) -> dict | None:
    positions = assets.get("positions")
    if not isinstance(positions, list) or not positions or not all(isinstance(p, dict) for p in positions):
        return None
    if any(not isinstance(p.get("extra", {}), dict) for p in positions):
        return None
    if any("market_value_provenance" in p or "market_value_provenance" in p.get("extra", {}) for p in positions):
        return None
    # A legacy CTP converter stored PositionCost as market_value and derived avg_price
    # from that same cost. Never overwrite a value already priced by a later converter.
    for position in positions:
        volume = _number(position.get("volume"))
        cost = _number(position.get("market_value"))
        avg = _number(position.get("avg_price"))
        extra_cost = _number(position.get("extra", {}).get("position_cost"))
        if (
            volume is None
            or cost is None
            or (extra_cost is not None and not math.isclose(cost, extra_cost, abs_tol=1e-6))
        ):
            return None
        if avg is not None and avg <= 0:
            return None
        if (
            avg is not None
            and volume > 0
            and avg > 0
            and not math.isclose(cost / volume / avg, round(cost / volume / avg), rel_tol=1e-6, abs_tol=1e-6)
        ):
            return None
        # Without a cost signature, a quote-matching value may already be price-marked.
        quote = quotes.get(position.get("symbol"))
        if (
            extra_cost is None
            and avg is None
            and quote
            and math.isclose(cost, abs(volume) * quote[0] * quote[1], rel_tol=1e-6)
        ):
            return None
    repaired = json.loads(json.dumps(assets))
    total = 0.0
    complete = True
    for position in repaired["positions"]:
        symbol = position.get("symbol")
        volume = _number(position.get("volume"))
        quote = quotes.get(symbol) if isinstance(symbol, str) else None
        cost = position["market_value"]
        extra = position.setdefault("extra", {})
        extra.setdefault("position_cost", cost)
        value = abs(volume) * quote[0] * quote[1] if volume is not None and quote else None
        if value is not None and math.isfinite(value):
            position["market_value"] = value
            extra["market_value_provenance"] = {"source": PROVENANCE, "quote_timestamp": quote[2]}
            total += value
        else:
            position["market_value"] = None
            extra["market_value_provenance"] = {"source": "unavailable", "quote_timestamp": None}
            complete = False
    repaired["market_value"] = total if complete and math.isfinite(total) else None
    return repaired


def _eligible(record: Mapping, account_channel: object) -> bool:
    raw = _document(record.get("raw_result"))
    declared = raw.get("channel_type", raw.get("channel")) if raw else None
    inputs = _document(record.get("raw_input"))
    if declared is None and inputs:
        declared = inputs.get("channel_type", inputs.get("channel"))
    return account_channel == "ctp" and (declared is None or str(declared).lower() == "ctp")


def _pages(connection: sa.Connection, statement, id_column):
    last_id = -1
    while True:
        rows = connection.execute(statement.where(id_column > last_id).order_by(id_column).limit(500)).mappings().all()
        if not rows:
            return
        yield from rows
        last_id = rows[-1]["id"]


def upgrade(connection: sa.Connection) -> None:
    """Repair joined CTP documents, preserving full original and expected JSON for guarded rollback."""
    metadata = sa.MetaData()
    records = sa.Table("executerecord", metadata, autoload_with=connection)
    snapshots = sa.Table("account_asset_snapshot", metadata, autoload_with=connection)
    artifacts = sa.Table("execution_artifact", metadata, autoload_with=connection)
    accounts = sa.Table("account", metadata, autoload_with=connection)
    backup = sa.Table(
        "axile_0014_market_value_backup",
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
    rows = _pages(
        connection,
        sa.select(records, accounts.c.trade_channel).join(accounts, records.c.account_id == accounts.c.id),
        records.c.id,
    )
    for row in rows:
        if not _eligible(row, row["trade_channel"]):
            continue
        result = _document(row["raw_result"])
        if result is None:
            continue
        quotes = _quotes(result)
        targets = [(records, row, "raw_result")]
        if row["execution_id"] is None:
            # NULL execution IDs cannot establish an unambiguous join to other observations.
            continue
        for table, predicate in (
            (snapshots, snapshots.c.account_id == row["account_id"]),
            (artifacts, artifacts.c.artifact_type.in_(["ACCOUNT_SNAPSHOT", "ACCOUNT_SNAPSHOT_BEFORE"])),
        ):
            targets.extend(
                (table, target, "assets" if table is snapshots else "content")
                for target in _pages(
                    connection,
                    sa.select(table).where(table.c.execution_id == row["execution_id"], predicate),
                    table.c.id,
                )
            )
        for table, target, column in targets:
            document = _document(target[column])
            if document is None:
                continue
            assets = document if column == "assets" else document.get("account_assets")
            if not isinstance(assets, dict):
                continue
            repaired = _repair(assets, quotes)
            if repaired is None:
                continue
            after = repaired if column == "assets" else {**document, "account_assets": repaired}
            connection.execute(
                backup.insert().values(
                    table_name=table.name,
                    row_id=target["id"],
                    json_column=column,
                    before=document,
                    after=after,
                    execution_id=row["execution_id"],
                )
            )
            connection.execute(table.update().where(table.c.id == target["id"]).values({column: after}))


def downgrade(connection: sa.Connection) -> None:
    """Restore only unchanged repaired documents; reject missing or externally edited rows."""
    metadata = sa.MetaData()
    backup = sa.Table("axile_0014_market_value_backup", metadata, autoload_with=connection)
    tables = {
        name: sa.Table(name, metadata, autoload_with=connection)
        for name in ("executerecord", "account_asset_snapshot", "execution_artifact")
    }
    # Validate the entire backup before applying any restoration.
    for entry in _pages(connection, sa.select(backup), backup.c.id):
        if entry["table_name"] not in tables:
            raise RuntimeError("0014 restore conflict: unknown table")
        table = tables[entry["table_name"]]
        row = connection.execute(sa.select(table).where(table.c.id == entry["row_id"])).mappings().first()
        if (
            row is None
            or row["execution_id"] != entry["execution_id"]
            or _document(row[entry["json_column"]]) != entry["after"]
        ):
            raise RuntimeError(f"0014 restore conflict: {entry['table_name']}:{entry['row_id']}")
    for entry in _pages(connection, sa.select(backup), backup.c.id):
        table = tables[entry["table_name"]]
        connection.execute(
            table.update().where(table.c.id == entry["row_id"]).values({entry["json_column"]: entry["before"]})
        )
    backup.drop(connection)

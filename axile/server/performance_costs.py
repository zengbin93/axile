"""Execution cost projection, preserving the historical UI's unknown-value rules."""

import math
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def timestamp(value: str) -> float:
    """Interpret historical naive timestamps as Shanghai time, in milliseconds."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=SHANGHAI).timestamp() * 1000 if parsed.tzinfo is None else parsed.timestamp() * 1000


def number(value: Any) -> float | None:
    """Match the UI's finite numeric string handling without treating bool as money."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def positive(value: Any) -> float | None:
    """Return a strictly positive finite value."""
    result = number(value)
    return result if result is not None and result > 0 else None


def mapping(value: Any) -> dict:
    """Normalize optional historical objects."""
    return value if isinstance(value, dict) else {}


def sequence(value: Any) -> list:
    """Normalize optional historical arrays."""
    return value if isinstance(value, list) else []


def side_of(value: Any) -> str:
    """Only explicit buy/sell directions are known."""
    value = value.lower() if isinstance(value, str) else None
    return value if value in ("buy", "sell") else "none"


def _trade(raw: Any, symbol: str, result: dict, orders: dict, created_at: str) -> dict:
    trade = mapping(raw)
    extra, tick = mapping(trade.get("extra")), mapping(result.get("first_tick"))
    bid, ask = positive(tick.get("bid_price")), positive(tick.get("ask_price"))
    mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else None
    reference = mid if mid is not None else positive(tick.get("last_price"))
    multiplier = positive(mapping(result.get("sizing")).get("unit_multiplier"))
    price, quantity = positive(trade.get("trade_price")), positive(trade.get("trade_volume"))
    side = orders.get(str(trade.get("order_id")), "none")
    if side == "none":
        side = side_of(extra.get("direction"))
    value = price * quantity * multiplier if price and quantity and multiplier else None
    signed_difference = (
        (price - reference) * (1 if side == "buy" else -1) if price and reference and side != "none" else None
    )
    try:
        time = timestamp(trade["trade_time"])
        estimated = False
    except (KeyError, ValueError, TypeError):
        time, estimated = timestamp(created_at), True
    currency = extra.get("commission_asset")
    return {
        "symbol": symbol,
        "day": datetime.fromtimestamp(time / 1000, SHANGHAI).date().isoformat(),
        "time": time,
        "timeEstimated": estimated,
        "side": side,
        "quantity": quantity,
        "price": price,
        "reference": reference,
        "referenceSource": "mid" if mid is not None else "last" if reference else None,
        "value": value,
        "cost": signed_difference * quantity * multiplier
        if quantity is not None and multiplier is not None and signed_difference is not None
        else None,
        "lossBp": signed_difference / reference * 1e4
        if signed_difference is not None and reference is not None
        else None,
        "fee": number(extra.get("commission")),
        "feeCurrency": currency if isinstance(currency, str) and currency.strip() else None,
    }


def project_execution(record) -> tuple[dict, list[dict]]:
    """Strip large raw JSON after extracting costs, status and record identity."""
    raw = mapping(record.raw_result)
    results = {symbol: mapping(value) for symbol, value in mapping(raw.get("symbol_results")).items()}
    trades = []
    has_fill = False
    for symbol, result in results.items():
        orders = {
            str(mapping(order).get("order_id")): side_of(mapping(order).get("direction"))
            for order in sequence(result.get("orders"))
        }
        trades.extend(
            _trade(trade, symbol, result, orders, record.created_at) for trade in sequence(result.get("trades"))
        )
        has_fill |= any(
            (number(mapping(order).get("filled_volume")) or 0) > 0 for order in sequence(result.get("orders"))
        )
    noop = (
        record.is_success == 1
        and not trades
        and not has_fill
        and (
            raw.get("status") == "NOOP"
            or bool(results)
            and all(result.get("status") == "NOOP" for result in results.values())
        )
    )
    payload = {
        "key": str(record.id),
        "record": {
            "id": record.id,
            "execution_id": record.execution_id,
            "created_at": record.created_at,
            "is_success": record.is_success,
            "raw_result": {key: raw[key] for key in ("status", "task_status") if key in raw},
        },
        "noop": noop,
        "symbolCount": len({trade["symbol"] for trade in trades if trade["quantity"] is not None}),
    }
    return payload, trades


def summarize(trades: list[dict]) -> dict:
    """Use amount-weighted loss BP, separate fee currencies and partial coverage."""
    valued = [trade for trade in trades if trade["value"] is not None]
    valid = [trade for trade in valued if trade["cost"] is not None]
    value = sum(trade["value"] for trade in valued)
    covered_value = sum(trade["value"] for trade in valid)
    fees: dict[str, float] = defaultdict(float)
    fee_covered = 0
    for trade in trades:
        if trade["fee"] is not None and trade["feeCurrency"]:
            fees[trade["feeCurrency"]] += trade["fee"]
            fee_covered += 1
    return {
        "value": value if valued else None,
        "cost": sum(trade["cost"] for trade in valid) if valid else None,
        "lossBp": sum(trade["lossBp"] * trade["value"] for trade in valid) / covered_value
        if covered_value > 0
        else None,
        "coverage": covered_value / value if len(valued) == len(trades) and value > 0 else None,
        "covered": len(valid),
        "count": len(trades),
        "amountComplete": len(valued) == len(trades),
        "fees": dict(fees),
        "feeCovered": fee_covered,
    }


def daily_costs(trades: list[dict]) -> dict[str, dict]:
    """Group trades by their actual Shanghai date, including cross-day fills."""
    groups = defaultdict(list)
    for trade in trades:
        groups[trade["day"]].append(trade)
    return {day: summarize(group) for day, group in groups.items()}

"""账户分析上下文测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from axile.server.context import Context
from axile.server.db.models import ExecuteRecord


def _record(
    *,
    created_at: str,
    total_asset: float,
    market_value: float = 0.0,
    available_cash: float = 0.0,
    positions: list[dict[str, object]] | None = None,
) -> ExecuteRecord:
    return ExecuteRecord(
        id=1,
        account_id=1,
        strategy_config=[],
        raw_input={},
        raw_result={
            "account_assets": {
                "total_asset": total_asset,
                "market_value": market_value,
                "available_cash": available_cash,
                "positions": positions or [],
            }
        },
        is_success=1,
        created_at=created_at,
    )


def test_has_data_and_execution_count_follow_loaded_records() -> None:
    context = Context(session=object(), account_id=1)
    context._records = []  # pyright: ignore[reportPrivateUsage]
    assert context.has_data() is False
    assert context.get_execution_count() == 0

    context._records = [_record(created_at=datetime.now().strftime("%Y-%m-%dT10:00:00"), total_asset=100.0)]  # pyright: ignore[reportPrivateUsage]
    assert context.has_data() is True
    assert context.get_execution_count() == 1


def test_today_return_uses_first_and_last_total_asset() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    context = Context(session=object(), account_id=1)
    context._records = [  # pyright: ignore[reportPrivateUsage]
        _record(created_at=f"{today}T09:00:00", total_asset=100.0),
        _record(created_at=f"{today}T15:00:00", total_asset=125.0),
    ]

    assert context.today_return == pytest.approx(0.25)


def test_today_return_is_zero_with_only_previous_day_baseline() -> None:
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    context = Context(session=object(), account_id=1)
    context._records = [  # pyright: ignore[reportPrivateUsage]
        _record(created_at=f"{yesterday}T15:00:00", total_asset=100.0),
    ]

    assert context.today_return == 0.0


def test_today_max_drawdown_tracks_peak_to_trough() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    context = Context(session=object(), account_id=1)
    context._records = [  # pyright: ignore[reportPrivateUsage]
        _record(created_at=f"{today}T09:00:00", total_asset=100.0),
        _record(created_at=f"{today}T10:00:00", total_asset=120.0),
        _record(created_at=f"{today}T11:00:00", total_asset=90.0),
        _record(created_at=f"{today}T14:00:00", total_asset=110.0),
    ]

    assert context.today_max_drawdown == pytest.approx(0.25)


def test_position_and_balance_metrics_use_latest_account_assets() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    context = Context(session=object(), account_id=1)
    context._records = [  # pyright: ignore[reportPrivateUsage]
        _record(
            created_at=f"{today}T15:00:00",
            total_asset=200.0,
            market_value=150.0,
            available_cash=50.0,
            positions=[
                {"direction": "多头", "market_value": 120.0},
                {"direction": "空头", "market_value": 30.0},
                {"direction": "其他", "market_value": 999.0},
            ],
        )
    ]

    assert context.current_leverage == pytest.approx(0.75)
    assert context.long_market_value == 120.0
    assert context.short_market_value == 30.0
    assert context.net_market_value == 90.0
    assert context.available_balance == 50.0
    assert context.frozen_funds == 150.0
    assert context.total_balance == 200.0
    assert context.used_margin == 150.0


def test_yesterday_total_balance_uses_previous_success_record(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context(session=object(), account_id=1)
    previous = _record(created_at="2026-03-21T15:00:00", total_asset=88.5)

    def fake_previous_last() -> ExecuteRecord:
        context._yesterday_last = previous  # pyright: ignore[reportPrivateUsage]
        return previous

    monkeypatch.setattr(context, "_get_previous_last_record", fake_previous_last)

    assert context.yesterday_total_balance == 88.5

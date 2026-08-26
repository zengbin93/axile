"""账户 dashboard 聚合路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.server.api.deps import get_db, get_scheduler
from axile.server.api.routes import account as account_routes
from axile.server.api.routes import account_crud
from tests.unit.server._execution_test_support import build_account


class _Result:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return self._items


class _Session:
    def __init__(self, accounts: list[object]) -> None:
        self._accounts = accounts

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self._accounts)


class _Job:
    def __init__(self, next_run_time: datetime | None) -> None:
        self.next_run_time = next_run_time


class _Scheduler:
    def __init__(self, job: _Job | None = None) -> None:
        self._job = job

    def get_job(self, _job_id: str) -> _Job | None:
        return self._job


def _build_app(session: _Session, scheduler: _Scheduler) -> FastAPI:
    app = FastAPI()
    app.include_router(account_routes.router)

    async def _override_get_db() -> AsyncGenerator[_Session, None]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    return app


def _record(
    total_asset: float,
    positions: list[dict[str, object]],
    currency: str,
    is_success: int,
    created_at: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        raw_result={
            "account_assets": {
                "total_asset": total_asset,
                "positions": positions,
                "currency": currency,
            }
        },
        raw_input={},
        is_success=is_success,
        created_at=created_at,
    )


def _snapshot(
    total_asset: float,
    positions: list[dict[str, object]],
    created_at: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        assets={"total_asset": total_asset, "positions": positions},
        created_at=created_at,
    )


def test_dashboard_aggregates_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """聚合最新权益/持仓/权益序列/绑定/下次执行/上次成败。"""
    account = build_account(id=1, name="acc", is_started=True)
    recent = [
        _record(
            102.0,
            [
                {"symbol": "rb2610", "market_value": 60000},
                {"symbol": "ag2612", "market_value": 40000},
            ],
            "CNY",
            1,
            "2026-07-02 09:03:00",
        ),
        _record(100.0, [{"symbol": "rb2610", "market_value": 50000}], "CNY", 1, "2026-07-02 09:00:00"),
    ]
    snapshots = [
        _snapshot(
            102.0,
            [
                {"symbol": "rb2610", "market_value": 60000},
                {"symbol": "ag2612", "market_value": 40000},
            ],
            "2026-07-02T09:03:00",
        ),
        _snapshot(100.0, [{"symbol": "rb2610", "market_value": 50000}], "2026-07-02T09:00:00"),
    ]

    async def _bindings(_session: object) -> dict[int, int]:
        return {1: 7}

    async def _recent(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {1: list(recent)}

    async def _snapshots(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {1: list(snapshots)}

    async def _no_baseline_records(*_args: object, **_kwargs: object) -> dict[int, list[object]]:
        return {}

    monkeypatch.setattr(account_crud, "get_portfolios_every_account", _bindings)
    monkeypatch.setattr(account_crud, "get_recent_execute_records_for_accounts", _recent)
    monkeypatch.setattr(account_crud, "get_recent_account_asset_snapshots_for_accounts", _snapshots)
    # 「今日涨跌」的基准查询走独立数据访问函数；假 session 对任意查询都返回账户对象，
    # 故在数据访问层桩掉基准记录（本用例不校验 today_pct）。
    monkeypatch.setattr(account_crud, "get_account_asset_snapshots_before_for_accounts", _no_baseline_records)
    monkeypatch.setattr(account_crud, "get_earliest_account_asset_snapshots_since_for_accounts", _no_baseline_records)

    async def _no_targets(_session: object, _pairs: object) -> dict[int, object]:
        return {}

    monkeypatch.setattr(account_crud, "get_latest_account_target_snapshots_for_accounts", _no_targets)

    app = _build_app(_Session([account]), _Scheduler(_Job(None)))
    response = TestClient(app).get("/account/dashboard")

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    item = data[0]
    assert item["account_id"] == 1
    assert item["portfolio_id"] == 7
    assert item["total_asset"] == 102.0
    assert item["currency"] == "CNY"  # CTP 渠道币种由渠道决定
    assert item["holdings_count"] == 2
    assert item["position_weights"] == [60000.0, 40000.0]  # 降序
    assert item["equity_series"] == [100.0, 102.0]  # 升序:旧→新
    assert item["asset_observed_at"] == "2026-07-02T09:03:00"
    assert item["last_is_success"] == 1
    assert item["last_output_status"] is None
    assert item["off_symbol_count"] is None
    assert item["is_scheduled"] is True
    assert item["next_run_time"] is None


def test_dashboard_handles_account_without_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """无执行记录的账户回退为零权益/空持仓/渠道币种。"""
    account = build_account(id=2, name="empty", is_started=False)

    async def _bindings(_session: object) -> dict[int, int]:
        return {}

    async def _recent(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {}

    async def _no_baseline_records(*_args: object, **_kwargs: object) -> dict[int, list[object]]:
        return {}

    monkeypatch.setattr(account_crud, "get_portfolios_every_account", _bindings)
    monkeypatch.setattr(account_crud, "get_recent_execute_records_for_accounts", _recent)
    monkeypatch.setattr(account_crud, "get_recent_account_asset_snapshots_for_accounts", _recent)
    monkeypatch.setattr(account_crud, "get_account_asset_snapshots_before_for_accounts", _no_baseline_records)
    monkeypatch.setattr(account_crud, "get_earliest_account_asset_snapshots_since_for_accounts", _no_baseline_records)

    async def _no_targets(_session: object, _pairs: object) -> dict[int, object]:
        return {}

    monkeypatch.setattr(account_crud, "get_latest_account_target_snapshots_for_accounts", _no_targets)

    app = _build_app(_Session([account]), _Scheduler(job=None))
    response = TestClient(app).get("/account/dashboard")

    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["total_asset"] == 0.0
    assert item["currency"] == "CNY"  # 无执行记录也由 CTP 渠道决定币种
    assert item["holdings_count"] == 0
    assert item["position_weights"] == []
    assert item["equity_series"] == []
    assert item["asset_observed_at"] is None
    assert item["last_is_success"] is None
    assert item["last_output_status"] is None
    assert item["off_symbol_count"] is None
    assert item["is_scheduled"] is False


def test_dashboard_counts_off_symbols_from_target_and_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """有持仓快照和目标时，off_symbol_count 按可执行数量口径计算。"""
    account = build_account(id=1, name="acc", is_started=True)
    snapshots = [
        _snapshot(
            1000.0,
            [{"symbol": "RM611", "market_value": 460, "direction": "空头"}],
            "2026-08-26T20:34:00",
        )
    ]
    records = [
        SimpleNamespace(
            raw_result={"status": "BLOCKED", "error": "5 个品种因交易时段不可执行"},
            raw_input={},
            is_success=0,
            created_at="2026-08-26T20:34:30",
        )
    ]

    async def _bindings(_session: object) -> dict[int, int]:
        return {1: 7}

    async def _recent(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {1: list(records)}

    async def _snapshots(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {1: list(snapshots)}

    async def _no_baseline_records(*_args: object, **_kwargs: object) -> dict[int, list[object]]:
        return {}

    async def _targets(_session: object, _pairs: object) -> dict[int, object]:
        return {
            1: SimpleNamespace(
                normalized_weights={"TA701": -0.07, "c2611": 0.03, "m2701": -0.06, "rb2610": 0.12},
            )
        }

    monkeypatch.setattr(account_crud, "get_portfolios_every_account", _bindings)
    monkeypatch.setattr(account_crud, "get_recent_execute_records_for_accounts", _recent)
    monkeypatch.setattr(account_crud, "get_recent_account_asset_snapshots_for_accounts", _snapshots)
    monkeypatch.setattr(account_crud, "get_account_asset_snapshots_before_for_accounts", _no_baseline_records)
    monkeypatch.setattr(account_crud, "get_earliest_account_asset_snapshots_since_for_accounts", _no_baseline_records)
    monkeypatch.setattr(account_crud, "get_latest_account_target_snapshots_for_accounts", _targets)

    app = _build_app(_Session([account]), _Scheduler(_Job(None)))
    item = TestClient(app).get("/account/dashboard").json()["data"][0]
    assert item["last_output_status"] == "BLOCKED"
    assert item["off_symbol_count"] == 5


def test_dashboard_counts_off_symbols_zero_when_lots_already_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """手数已按渠道量化到位（含 TA2701→TA701）时 off_symbol_count 为 0。"""
    account = build_account(id=1, name="acc", is_started=True)
    equity = 992_670.6124999999
    snapshots = [
        _snapshot(
            equity,
            [
                {
                    "symbol": "c2611",
                    "volume": 1.0,
                    "market_value": 22800.0,
                    "direction": "多头",
                    "extra": {"net_position": 1.0},
                },
                {
                    "symbol": "rb2610",
                    "volume": 4.0,
                    "market_value": 123100.0,
                    "direction": "多头",
                    "extra": {"net_position": 4.0},
                },
                {
                    "symbol": "TA701",
                    "volume": 2.0,
                    "market_value": 55000.0,
                    "direction": "空头",
                    "extra": {"net_position": -2.0},
                },
                {
                    "symbol": "m2701",
                    "volume": 1.0,
                    "market_value": 32960.0,
                    "direction": "空头",
                    "extra": {"net_position": -1.0},
                },
            ],
            "2026-08-26T21:35:11",
        )
    ]
    records = [
        SimpleNamespace(
            raw_result={"status": "SUCCEEDED"},
            raw_input={},
            is_success=1,
            created_at="2026-08-26T21:35:11",
        )
    ]

    async def _bindings(_session: object) -> dict[int, int]:
        return {1: 7}

    async def _recent(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {1: list(records)}

    async def _snapshots(_session: object, _account_ids: object, limit: int = 20) -> dict[int, list[object]]:
        return {1: list(snapshots)}

    async def _no_baseline_records(*_args: object, **_kwargs: object) -> dict[int, list[object]]:
        return {}

    async def _targets(_session: object, _pairs: object) -> dict[int, object]:
        return {
            1: SimpleNamespace(
                normalized_weights={"TA2701": -0.08, "c2611": 0.03, "m2701": -0.06, "rb2610": 0.13},
            )
        }

    monkeypatch.setattr(account_crud, "get_portfolios_every_account", _bindings)
    monkeypatch.setattr(account_crud, "get_recent_execute_records_for_accounts", _recent)
    monkeypatch.setattr(account_crud, "get_recent_account_asset_snapshots_for_accounts", _snapshots)
    monkeypatch.setattr(account_crud, "get_account_asset_snapshots_before_for_accounts", _no_baseline_records)
    monkeypatch.setattr(account_crud, "get_earliest_account_asset_snapshots_since_for_accounts", _no_baseline_records)
    monkeypatch.setattr(account_crud, "get_latest_account_target_snapshots_for_accounts", _targets)

    app = _build_app(_Session([account]), _Scheduler(_Job(None)))
    item = TestClient(app).get("/account/dashboard").json()["data"][0]
    assert item["off_symbol_count"] == 0

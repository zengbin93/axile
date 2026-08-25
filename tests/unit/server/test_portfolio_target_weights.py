"""组合目标权重快照路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.server.api.deps import get_db
from axile.server.api.routes import portfolio as portfolio_routes
from axile.server.db.models import Portfolio, TargetWeightSnapshot


class _RouteSession:
    """组合快照路由所需的最小异步会话。"""

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    async def get(self, model: object, obj_id: int) -> object | None:
        if model is Portfolio and self.portfolio.id == obj_id:
            return self.portfolio
        return None


def _build_portfolio() -> Portfolio:
    return Portfolio(
        id=7,
        name="combo",
        market="加密货币",
        description="desc",
        custom_calc_py_code="def calculate_portfolio(context):\n    return {'BTCUSDT': 0.6}\n",
        status="active",
        tag="core",
    )


def _build_app(session: _RouteSession) -> FastAPI:
    app = FastAPI()
    app.include_router(portfolio_routes.router)

    async def _override_get_db() -> AsyncGenerator[_RouteSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    return app


def test_portfolio_latest_weights_get_only_reads_snapshot(monkeypatch) -> None:
    """兼容 GET 只读已有快照，不执行自定义组合函数。"""
    session = _RouteSession(_build_portfolio())

    async def fake_latest(_session: object, _portfolio_id: int) -> TargetWeightSnapshot:
        return TargetWeightSnapshot(
            id=2,
            portfolio_id=7,
            raw_weights={"BTCUSDT": 0.6},
            source="manual",
            calculated_at="2026-08-25T10:00:00",
        )

    async def fail_if_resolved(*_args: object) -> dict[str, float]:
        raise AssertionError("GET must not execute calculate_portfolio")

    monkeypatch.setattr(portfolio_routes, "get_latest_portfolio_target_snapshot", fake_latest)
    monkeypatch.setattr(portfolio_routes, "resolve_portfolio_target", fail_if_resolved)

    response = TestClient(_build_app(session)).get("/portfolio/latest_weights/7")

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 0.6}


def test_refresh_portfolio_target_snapshot_calculates_and_persists(monkeypatch) -> None:
    """显式 POST 应执行组合函数并保存原始目标快照。"""
    session = _RouteSession(_build_portfolio())
    saved: list[dict[str, object]] = []

    async def fake_account_id(_session: object, _portfolio_id: int) -> None:
        return None

    async def fake_resolve(_portfolio: Portfolio, _context: object) -> dict[str, float]:
        return {"BTCUSDT": 0.6}

    async def fake_append(_session: object, **kwargs: object) -> TargetWeightSnapshot:
        saved.append(kwargs)
        return TargetWeightSnapshot(id=3, calculated_at="2026-08-25T10:30:00", **kwargs)

    monkeypatch.setattr(portfolio_routes, "get_latest_account_id_by_portfolio_id", fake_account_id)
    monkeypatch.setattr(portfolio_routes, "resolve_portfolio_target", fake_resolve)
    monkeypatch.setattr(portfolio_routes, "append_target_weight_snapshot", fake_append)

    response = TestClient(_build_app(session)).post("/portfolio/7/target_snapshot/refresh")

    assert response.status_code == 200
    assert response.json()["weights"] == {"BTCUSDT": 0.6}
    assert saved == [
        {
            "portfolio_id": 7,
            "account_id": None,
            "raw_weights": {"BTCUSDT": 0.6},
            "normalized_weights": None,
            "source": "manual",
        }
    ]

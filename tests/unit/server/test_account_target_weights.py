"""账户级「执行器口径」目标权重接口的路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.common.trade_channel import TradeChannel
from axile.server.api.deps import get_db
from axile.server.api.routes import account as account_routes
from axile.server.api.routes import account_execution as account_execution_routes
from axile.server.db.models import Account, Portfolio


class _RouteSession:
    """支持按模型区分 ``get(Account, id)`` 与 ``get(Portfolio, id)`` 的极简会话。"""

    def __init__(self, account: Account | None, portfolio: Portfolio | None) -> None:
        self._account = account
        self._portfolio = portfolio

    async def get(self, model: object, obj_id: int) -> object | None:
        if model is Account:
            if self._account is not None and self._account.id == obj_id:
                return self._account
            return None
        if model is Portfolio:
            if self._portfolio is not None and self._portfolio.id == obj_id:
                return self._portfolio
            return None
        return None


def _build_account(
    *,
    long_leverage: float | None = 3.0,
    short_leverage: float | None = 3.0,
    weight_precision: float = 0.01,
) -> Account:
    return Account(
        id=1,
        name="ctp-testnet-sim",
        market="加密货币",
        trade_channel=TradeChannel.CTP,
        account_config={"api_key": "k", "secret_key": "s", "is_testnet": True},
        is_started=True,
        cron_expr="3,6,9 * * * *",
        remark=None,
        brokerage="ctp",
        weight_precision=weight_precision,
        long_leverage=long_leverage,
        short_leverage=short_leverage,
        algorithm={"method": "SINGLE-MAKER", "params": {}},
        trade_rules={},
        forbidden_symbols=[],
        risk_symbols=[],
        feishu_key=None,
        portfolio_id=7,
        write_empty_record=0,
    )


def _build_portfolio() -> Portfolio:
    return Portfolio(
        id=7,
        name="combo",
        market="加密货币",
        description="desc",
        custom_calc_py_code="def calculate_portfolio(context):\n    return {}\n",
        status="active",
        tag="core",
    )


def _build_app(session: _RouteSession) -> FastAPI:
    app = FastAPI()
    app.include_router(account_routes.router)

    async def _override_get_db() -> AsyncGenerator[_RouteSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    return app


def _patch_resolution(
    monkeypatch,
    *,
    portfolio_id: int | None,
    raw_target: dict[str, float],
) -> None:
    """桩掉绑定组合解析与裸目标合成，把测试聚焦在杠杆缩放这一层。"""

    async def fake_get_latest_portfolio_id_by_account_id(_session: object, _account_id: int) -> int | None:
        return portfolio_id

    async def fake_resolve_portfolio_target(_portfolio: Portfolio, _context: object) -> dict[str, float]:
        return dict(raw_target)

    monkeypatch.setattr(
        account_execution_routes,
        "get_latest_portfolio_id_by_account_id",
        fake_get_latest_portfolio_id_by_account_id,
    )
    monkeypatch.setattr(account_execution_routes, "resolve_portfolio_target", fake_resolve_portfolio_target)


def test_account_target_weights_applies_long_leverage(monkeypatch) -> None:
    """多头目标应按 ``long_leverage`` 放大：策略净 50% × 3x → 展示 150%。"""
    session = _RouteSession(_build_account(long_leverage=3.0), _build_portfolio())
    _patch_resolution(monkeypatch, portfolio_id=7, raw_target={"BTCUSDT": 0.5, "ETHUSDT": 0.5})

    response = TestClient(_build_app(session)).get("/account/1/target_weights")

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 1.5, "ETHUSDT": 1.5}


def test_account_target_weights_applies_short_leverage(monkeypatch) -> None:
    """空头目标（负权重）按 ``short_leverage`` 放大，多空各用各的乘数。"""
    session = _RouteSession(_build_account(long_leverage=1.0, short_leverage=2.0), _build_portfolio())
    _patch_resolution(monkeypatch, portfolio_id=7, raw_target={"BTCUSDT": 0.5, "ETHUSDT": -0.5})

    response = TestClient(_build_app(session)).get("/account/1/target_weights")

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 0.5, "ETHUSDT": -1.0}


def test_account_target_weights_falls_back_to_channel_default_leverage(monkeypatch) -> None:
    """杠杆为 ``None`` 时回落到渠道默认（CTP 多头默认 3x）。"""
    session = _RouteSession(_build_account(long_leverage=None, short_leverage=None), _build_portfolio())
    _patch_resolution(monkeypatch, portfolio_id=7, raw_target={"BTCUSDT": 0.5})

    response = TestClient(_build_app(session)).get("/account/1/target_weights")

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 1.5}


def test_account_target_weights_returns_empty_without_bound_portfolio(monkeypatch) -> None:
    """账户未绑定组合时返回空映射，交由前端降级。"""
    session = _RouteSession(_build_account(), _build_portfolio())
    _patch_resolution(monkeypatch, portfolio_id=None, raw_target={"BTCUSDT": 0.5})

    response = TestClient(_build_app(session)).get("/account/1/target_weights")

    assert response.status_code == 200
    assert response.json() == {}


def test_account_target_weights_returns_404_for_unknown_account(monkeypatch) -> None:
    """账户不存在时返回 404。"""
    session = _RouteSession(None, _build_portfolio())
    _patch_resolution(monkeypatch, portfolio_id=7, raw_target={"BTCUSDT": 0.5})

    response = TestClient(_build_app(session)).get("/account/999/target_weights")

    assert response.status_code == 404

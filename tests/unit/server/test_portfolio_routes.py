"""组合路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.common.trade_channel import TradeChannel
from axile.server.api.deps import get_db
from axile.server.api.routes import portfolio as portfolio_routes
from axile.server.db.models import Portfolio, StrategyConfig


@pytest.fixture(autouse=True)
def _default_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认让量化数据源就绪.

    组合创建/更新与策略权重路径受 ``settings.quant_data_api`` 门禁约束（无数据源仅允许
    自定义组合）。测试进程的 ``config.toml`` 属本机产物、CI 不存在，故在此显式置为非空，
    使策略型组合用例结果确定；需要「无数据源」场景的用例在内部另行置空覆盖。
    """
    monkeypatch.setattr(portfolio_routes.settings, "quant_data_api", "http://data.test")


class _FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, *, scalar_value: object | None = None, rows: list[object] | None = None) -> None:
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar_one(self) -> object:
        return self._scalar_value

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _RouteSession:
    def __init__(
        self,
        *,
        portfolios: list[Portfolio] | None = None,
        execute_results: list[_FakeExecuteResult] | None = None,
    ) -> None:
        self.portfolios = {portfolio.id: portfolio for portfolio in portfolios or []}
        self.execute_results = list(execute_results or [])
        self.added: list[object] = []
        self.deleted: list[Portfolio] = []
        self.rollback_count = 0

    async def get(self, _model: object, portfolio_id: int) -> Portfolio | None:
        return self.portfolios.get(portfolio_id)

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, Portfolio) and obj.id is not None:
            self.portfolios[obj.id] = obj

    async def flush(self) -> None:
        for obj in self.added:
            if isinstance(obj, Portfolio) and obj.id is None:
                obj.id = 1
                self.portfolios[obj.id] = obj

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def delete(self, portfolio: Portfolio) -> None:
        self.deleted.append(portfolio)

    async def execute(self, _statement: object) -> _FakeExecuteResult:
        return self.execute_results.pop(0)


def _strategy(name: str, weight: float, base_freq: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {"name": name, "weight": weight}
    if base_freq is not None:
        item["base_freq"] = base_freq
    return item


def _build_portfolio(*, portfolio_id: int = 1, name: str = "combo") -> Portfolio:
    return Portfolio(
        id=portfolio_id,
        name=name,
        market="加密货币",
        description="desc",
        custom_calc_py_code=None,
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


def test_create_portfolio_returns_full_public_model(monkeypatch) -> None:
    session = _RouteSession()

    def fake_add_strategies_by_portfolio_id(
        _session: object, portfolio_id: int | None, strategies: list[dict[str, object]]
    ) -> StrategyConfig:
        return StrategyConfig(
            id=11, portfolio_id=portfolio_id or 0, strategies=strategies, created_at="2026-03-22T18:00:00"
        )

    monkeypatch.setattr(portfolio_routes, "add_strategies_by_portfolio_id", fake_add_strategies_by_portfolio_id)

    response = TestClient(_build_app(session)).post(
        "/portfolio/",
        json={
            "name": "alpha",
            "market": "加密货币",
            "description": "desc",
            "custom_calc_py_code": None,
            "status": "active",
            "tag": "core",
            "strategies": [_strategy("s1", 0.6), _strategy("s2", 0.4)],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "alpha"
    assert body["strategy_config"] == [_strategy("s1", 0.6), _strategy("s2", 0.4)]
    assert body["account_id"] is None


def test_list_portfolios_returns_lite_payloads() -> None:
    portfolios = [_build_portfolio(portfolio_id=1, name="alpha"), _build_portfolio(portfolio_id=2, name="beta")]
    session = _RouteSession(execute_results=[_FakeExecuteResult(rows=portfolios)])

    response = TestClient(_build_app(session)).get("/portfolio/")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["data"]] == ["alpha", "beta"]


def test_portfolio_info_returns_latest_strategy_config_and_bound_account(monkeypatch) -> None:
    session = _RouteSession(portfolios=[_build_portfolio(portfolio_id=1)])

    async def fake_get_portfolio_strategies_and_account(
        _session: object, _portfolio_id: int
    ) -> tuple[list[dict[str, object]], int]:
        return ([_strategy("alpha", 1.0)], 7)

    monkeypatch.setattr(
        portfolio_routes, "get_portfolio_strategies_and_account", fake_get_portfolio_strategies_and_account
    )

    response = TestClient(_build_app(session)).get("/portfolio/1")

    assert response.status_code == 200
    assert response.json()["strategy_config"] == [_strategy("alpha", 1.0)]
    assert response.json()["account_id"] == 7


def test_delete_portfolio_rejects_bound_portfolio(monkeypatch) -> None:
    portfolio = _build_portfolio(portfolio_id=1)
    session = _RouteSession(portfolios=[portfolio])

    async def fake_get_portfolios_every_account(_session: object) -> dict[int, int]:
        return {99: 1}

    monkeypatch.setattr(portfolio_routes, "get_portfolios_every_account", fake_get_portfolios_every_account)

    response = TestClient(_build_app(session)).delete("/portfolio/1")

    assert response.status_code == 422
    assert "必须解绑" in response.json()["detail"]
    assert session.deleted == []


def test_delete_portfolio_deletes_unbound_portfolio(monkeypatch) -> None:
    portfolio = _build_portfolio(portfolio_id=1)
    session = _RouteSession(portfolios=[portfolio])

    async def fake_get_portfolios_every_account(_session: object) -> dict[int, int]:
        return {99: 2}

    monkeypatch.setattr(portfolio_routes, "get_portfolios_every_account", fake_get_portfolios_every_account)

    response = TestClient(_build_app(session)).delete("/portfolio/1")

    assert response.status_code == 200
    assert response.json() == {"message": "成功删除组合"}
    assert session.deleted == [portfolio]


def test_update_portfolio_returns_updated_public_model(monkeypatch) -> None:
    portfolio = _build_portfolio(portfolio_id=1, name="before")
    session = _RouteSession(portfolios=[portfolio])
    added_strategy_calls: list[tuple[int, list[dict[str, object]]]] = []

    def fake_add_strategies_by_portfolio_id(
        _session: object, portfolio_id: int | None, strategies: list[dict[str, object]]
    ) -> StrategyConfig:
        added_strategy_calls.append((portfolio_id or 0, strategies))
        return StrategyConfig(
            id=12, portfolio_id=portfolio_id or 0, strategies=strategies, created_at="2026-03-22T18:00:00"
        )

    monkeypatch.setattr(portfolio_routes, "add_strategies_by_portfolio_id", fake_add_strategies_by_portfolio_id)

    async def fake_get_portfolio_strategies_and_account(
        _session: object,
        _portfolio_id: int,
    ) -> tuple[list[dict[str, object]], None]:
        return ([_strategy("fresh", 1.0)], None)

    monkeypatch.setattr(
        portfolio_routes, "get_portfolio_strategies_and_account", fake_get_portfolio_strategies_and_account
    )

    response = TestClient(_build_app(session)).patch(
        "/portfolio/1",
        json={"name": "after", "custom_calc_py_code": None, "strategies": [_strategy("fresh", 1.0)]},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "after"
    assert response.json()["strategy_config"] == [_strategy("fresh", 1.0)]
    assert added_strategy_calls == [(1, [_strategy("fresh", 1.0)])]


def test_create_portfolio_rejects_strategy_without_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """无数据源时创建策略型组合应 422（仅允许自定义组合）。"""
    monkeypatch.setattr(portfolio_routes.settings, "quant_data_api", "")

    response = TestClient(_build_app(_RouteSession())).post(
        "/portfolio/",
        json={
            "name": "alpha",
            "market": "加密货币",
            "description": "desc",
            "custom_calc_py_code": None,
            "status": "active",
            "tag": "core",
            "strategies": [_strategy("s1", 1.0)],
        },
    )

    assert response.status_code == 422
    assert "仅支持自定义组合" in response.json()["detail"]


def test_create_portfolio_allows_custom_without_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """无数据源时创建自定义组合应放行（不含策略、带脚本）。"""
    monkeypatch.setattr(portfolio_routes.settings, "quant_data_api", "")

    def fake_add_strategies_by_portfolio_id(
        _session: object, portfolio_id: int | None, strategies: list[dict[str, object]]
    ) -> StrategyConfig:
        return StrategyConfig(
            id=1, portfolio_id=portfolio_id or 0, strategies=strategies, created_at="2026-03-22T18:00:00"
        )

    monkeypatch.setattr(portfolio_routes, "add_strategies_by_portfolio_id", fake_add_strategies_by_portfolio_id)

    response = TestClient(_build_app(_RouteSession())).post(
        "/portfolio/",
        json={
            "name": "alpha",
            "market": "加密货币",
            "description": "desc",
            "custom_calc_py_code": "def calculate_portfolio(context):\n    return {'BTCUSDT': 1.0}",
            "status": "active",
            "tag": "core",
            "strategies": [],
        },
    )

    assert response.status_code == 201


def test_update_portfolio_rejects_adding_strategies_without_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """无数据源时给组合新增策略（并清空脚本）应 422。"""
    monkeypatch.setattr(portfolio_routes.settings, "quant_data_api", "")
    session = _RouteSession(portfolios=[_build_portfolio(portfolio_id=1)])

    response = TestClient(_build_app(session)).patch(
        "/portfolio/1",
        json={"strategies": [_strategy("s1", 1.0)], "custom_calc_py_code": None},
    )

    assert response.status_code == 422
    assert "仅支持自定义组合" in response.json()["detail"]


def test_latest_weights_reports_missing_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """无数据源时策略型组合查看目标应 422：护栏在 get_latest_weights 入口触发并被映射。"""
    monkeypatch.setattr(portfolio_routes.settings, "quant_data_api", "")
    session = _RouteSession(portfolios=[_build_portfolio(portfolio_id=1)])

    async def fake_get_latest_strategies_by_portfolio_id(_session: object, _portfolio_id: int) -> StrategyConfig:
        return StrategyConfig(
            id=1, portfolio_id=1, strategies=[_strategy("alpha", 1.0)], created_at="2026-03-22T18:00:00"
        )

    monkeypatch.setattr(
        portfolio_routes, "get_latest_strategies_by_portfolio_id", fake_get_latest_strategies_by_portfolio_id
    )

    response = TestClient(_build_app(session)).get("/portfolio/latest_weights/1?trade_channel=ctp")

    assert response.status_code == 422
    assert "数据源" in response.json()["detail"]


def test_list_strategies_records_returns_count_and_rows() -> None:
    portfolio = _build_portfolio(portfolio_id=1)
    records = [
        StrategyConfig(id=1, portfolio_id=1, strategies=[_strategy("alpha", 0.6)], created_at="2026-03-22T17:00:00"),
        StrategyConfig(id=2, portfolio_id=1, strategies=[_strategy("beta", 0.4)], created_at="2026-03-22T18:00:00"),
    ]
    session = _RouteSession(
        portfolios=[portfolio],
        execute_results=[
            _FakeExecuteResult(scalar_value=2),
            _FakeExecuteResult(rows=records),
        ],
    )

    response = TestClient(_build_app(session)).get("/portfolio/strategies_records/1?skip=0&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [item["id"] for item in body["data"]] == [1, 2]


def test_portfolio_latest_weights_returns_target_balance(monkeypatch) -> None:
    portfolio = _build_portfolio(portfolio_id=1)
    session = _RouteSession(portfolios=[portfolio])

    async def fake_get_latest_strategies_by_portfolio_id(_session: object, _portfolio_id: int) -> StrategyConfig:
        return StrategyConfig(
            id=1,
            portfolio_id=1,
            strategies=[_strategy("alpha", 0.6, "15m"), _strategy("beta", 0.4)],
            created_at="2026-03-22T18:00:00",
        )

    monkeypatch.setattr(
        portfolio_routes, "get_latest_strategies_by_portfolio_id", fake_get_latest_strategies_by_portfolio_id
    )

    async def fake_get_latest_weights(
        strategy_names: Any, strategy_freqs: dict[str, str] | None = None
    ) -> tuple[pd.DataFrame, str | None]:
        assert list(strategy_names) == ["alpha", "beta"]
        assert strategy_freqs == {"alpha": "15m"}
        return (
            pd.DataFrame(
                [
                    {"strategy": "alpha", "symbol": "BTCUSDT", "weight": 0.5},
                    {"strategy": "beta", "symbol": "ETHUSDT", "weight": 0.25},
                ]
            ),
            "2026-07-02T09:00:00",
        )

    def fake_get_target_balance(
        dfw: pd.DataFrame, strategy_config: dict[str, float], trade_channel: TradeChannel
    ) -> dict[str, float]:
        assert strategy_config == {"alpha": 0.6, "beta": 0.4}
        assert trade_channel == TradeChannel.CTP
        assert sorted(dfw["symbol"].tolist()) == ["BTCUSDT", "ETHUSDT"]
        return {"BTCUSDT": 0.3, "ETHUSDT": 0.1}

    monkeypatch.setattr(portfolio_routes, "get_latest_weights", fake_get_latest_weights)
    monkeypatch.setattr(portfolio_routes, "get_target_balance", fake_get_target_balance)

    response = TestClient(_build_app(session)).get(
        "/portfolio/latest_weights/1?trade_channel=ctp&weight_precision=0.01",
    )

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 0.3, "ETHUSDT": 0.1}


def test_portfolio_latest_weights_runs_custom_calc_code() -> None:
    """自定义逻辑组合应执行用户脚本, 不再因策略列表为空而报「策略配置为空」。"""
    portfolio = _build_portfolio(portfolio_id=7)
    portfolio.custom_calc_py_code = "def calculate_portfolio(context):\n    return {'BTCUSDT': 0.5, 'ETHUSDT': 0.5}"
    session = _RouteSession(portfolios=[portfolio])

    response = TestClient(_build_app(session)).get(
        "/portfolio/latest_weights/7?trade_channel=ctp",
    )

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 0.5, "ETHUSDT": 0.5}


def test_portfolio_latest_weights_reports_custom_calc_failure() -> None:
    """自定义脚本执行失败应返回 400, 并带上失败原因。"""
    portfolio = _build_portfolio(portfolio_id=8)
    portfolio.custom_calc_py_code = "def calculate_portfolio(context):\n    raise RuntimeError('boom')"
    session = _RouteSession(portfolios=[portfolio])

    response = TestClient(_build_app(session)).get(
        "/portfolio/latest_weights/8?trade_channel=ctp",
    )

    assert response.status_code == 400
    assert "boom" in response.json()["detail"]


def test_portfolio_preview_weights_synthesizes_without_persistence(monkeypatch) -> None:
    """preview_weights 应基于请求体里的策略配置合成目标, 不读库、不落库。"""
    session = _RouteSession()

    async def fake_get_latest_weights(
        strategy_names: Any, strategy_freqs: dict[str, str] | None = None
    ) -> tuple[pd.DataFrame, str | None]:
        assert list(strategy_names) == ["alpha", "beta"]
        assert strategy_freqs == {"alpha": "15m"}
        return (
            pd.DataFrame(
                [
                    {"strategy": "alpha", "symbol": "BTCUSDT", "weight": 0.5},
                    {"strategy": "beta", "symbol": "ETHUSDT", "weight": 0.25},
                ]
            ),
            "2026-07-02T09:00:00",
        )

    def fake_get_target_balance(
        dfw: pd.DataFrame, strategy_config: dict[str, float], trade_channel: TradeChannel
    ) -> dict[str, float]:
        assert strategy_config == {"alpha": 0.6, "beta": 0.4}
        assert trade_channel == TradeChannel.CTP
        return {"BTCUSDT": 0.3, "ETHUSDT": 0.1}

    monkeypatch.setattr(portfolio_routes, "get_latest_weights", fake_get_latest_weights)
    monkeypatch.setattr(portfolio_routes, "get_target_balance", fake_get_target_balance)

    response = TestClient(_build_app(session)).post(
        "/portfolio/preview_weights",
        json={
            "trade_channel": "ctp",
            "strategies": [_strategy("alpha", 0.6, "15m"), _strategy("beta", 0.4)],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"BTCUSDT": 0.3, "ETHUSDT": 0.1}


def test_portfolio_preview_weights_rejects_empty_config() -> None:
    """空策略配置应返回 404。"""
    response = TestClient(_build_app(_RouteSession())).post(
        "/portfolio/preview_weights",
        json={"trade_channel": "ctp", "strategies": []},
    )

    assert response.status_code == 404


class _AccountLookupSession:
    """仅支持 ``get(Account, id)`` 的极简会话, 用于 validate_custom_calc 真实账户路径。"""

    def __init__(self, existing_ids: set[int]) -> None:
        self.existing = set(existing_ids)

    async def get(self, _model: object, account_id: int) -> object | None:
        return object() if account_id in self.existing else None


def _validate_custom_calc(session: object, code: str, account_id: int | None = None) -> Any:
    """便捷封装: 对 validate_custom_calc 端点发起一次请求并返回 response。"""
    body: dict[str, object] = {"custom_calc_py_code": code}
    if account_id is not None:
        body["account_id"] = account_id
    return TestClient(_build_app(session)).post("/portfolio/validate_custom_calc", json=body)


def test_validate_custom_calc_dry_run_success() -> None:
    """Dry-run: 合法脚本应返回 valid=True 与目标权重, 且始终 200。"""
    code = "def calculate_portfolio(context):\n    return {'BTCUSDT': 0.5, 'ETHUSDT': 0.5}"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["target"] == {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    assert body["error"] is None
    assert body["traceback"] is None


def test_validate_custom_calc_dry_run_uses_sample_context() -> None:
    """Dry-run: 样例 context 提供齐全假值, 依赖 context 字段的脚本也能跑通 (不触库)。"""
    code = (
        "def calculate_portfolio(context):\n"
        "    w = 0.0 if context.consecutive_loss_days > 0 else 1.0\n"
        "    lev = context.current_leverage\n"
        "    return {'BTCUSDT': w if lev < 3 else 0.0}"
    )

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["target"] == {"BTCUSDT": 1.0}


def test_validate_custom_calc_reports_syntax_error() -> None:
    """Dry-run: 语法错误应返回 valid=False + traceback + 定位信息, HTTP 仍为 200。"""
    code = "def calculate_portfolio(context)\n    return {}"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["target"] is None
    assert "SyntaxError" in body["traceback"]
    assert body["error_type"] == "SyntaxError"
    assert body["error_line"] is not None


def test_validate_custom_calc_reports_runtime_error_with_line() -> None:
    """Dry-run: 运行时异常应定位到用户代码出错行, 并给出简洁消息。"""
    code = "def calculate_portfolio(context):\n    raise RuntimeError('boom')"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert "boom" in body["error"]
    assert "RuntimeError" in body["traceback"]
    # 出错行是用户代码第 2 行（raise 那一行），而非内部调用栈。
    assert body["error_line"] == 2
    assert body["error_type"] == "RuntimeError"
    assert "boom" in body["error_message"]


def test_validate_custom_calc_rejects_missing_function() -> None:
    """Dry-run: 缺少 calculate_portfolio 定义应判为无效。"""
    code = "x = 1"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert "calculate_portfolio" in body["error"]


def test_validate_custom_calc_rejects_bad_signature() -> None:
    """Dry-run: 签名不是单参数应判为无效。"""
    code = "def calculate_portfolio(a, b):\n    return {}"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_validate_custom_calc_rejects_non_dict_return() -> None:
    """Dry-run: 返回值不是权重字典应判为无效。"""
    code = "def calculate_portfolio(context):\n    return [1, 2, 3]"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert "dict" in body["error"]


def test_validate_custom_calc_rejects_non_finite_weight() -> None:
    """Dry-run: 权重出现非有限值 (NaN/inf) 应判为无效。"""
    code = "def calculate_portfolio(context):\n    return {'BTCUSDT': float('nan')}"

    response = _validate_custom_calc(_RouteSession(), code)

    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_validate_custom_calc_real_account_runs_with_context(monkeypatch) -> None:
    """真实账户: 账户存在时借真实 Context 执行脚本并返回权重。"""

    class _FakeCtxSession:
        async def __aenter__(self) -> _FakeCtxSession:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    monkeypatch.setattr(portfolio_routes, "SessionLocal", lambda: _FakeCtxSession())

    code = "def calculate_portfolio(context):\n    return {'BTCUSDT': 1.0}"
    response = _validate_custom_calc(_AccountLookupSession({5}), code, account_id=5)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["target"] == {"BTCUSDT": 1.0}


def test_validate_custom_calc_missing_account_returns_404() -> None:
    """真实账户: 指定不存在的账户应返回 404 (调用错误, 非脚本错误)。"""
    code = "def calculate_portfolio(context):\n    return {'BTCUSDT': 1.0}"

    response = _validate_custom_calc(_AccountLookupSession(set()), code, account_id=999)

    assert response.status_code == 404
    assert "账户不存在" in response.json()["detail"]

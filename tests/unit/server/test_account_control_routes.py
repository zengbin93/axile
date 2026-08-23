"""账户控制相关路由测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.registry import (
    ensure_default_account_control_registry_bootstrapped,
    reset_default_account_control_registry_for_tests,
)
from axile.server.api.deps import get_db, get_scheduler
from axile.server.api.routes import account as account_routes
from axile.server.api.routes import account_crud as account_crud_routes
from axile.server.db.models import Account


@pytest.fixture(autouse=True)
def _seed_account_control_registry() -> None:
    registry = reset_default_account_control_registry_for_tests()
    ensure_default_account_control_registry_bootstrapped()
    registry.freeze()


class _RouteSession:
    def __init__(self, account: Account | None = None) -> None:
        self.account = account
        self.rollback_count = 0

    async def get(self, _model: object, account_id: int) -> Account | None:
        if self.account is not None and self.account.id == account_id:
            return self.account
        return None

    def add(self, account: Account) -> None:
        self.account = account

    async def flush(self) -> None:
        if self.account is not None and self.account.id is None:
            self.account.id = 1

    async def commit(self) -> None:
        return None

    async def refresh(self, _account: Account) -> None:
        return None

    async def rollback(self) -> None:
        self.rollback_count += 1


class _Scheduler:
    def get_job(self, _job_id: str) -> None:
        return None


def _build_account(
    *,
    preset: str = "default",
    trade_channel: TradeChannel = TradeChannel.CTP,
    override: dict[str, object] | None = None,
) -> Account:
    return Account(
        id=1,
        name="ctp-testnet-sim",
        market="期货",
        trade_channel=trade_channel,
        account_config={
            "broker_id": "9999",
            "investor_id": "test",
            "password": "test",
            "td_front": "tcp://td:1",
            "md_front": "tcp://md:2",
            "app_id": "app",
            "auth_code": "auth",
        },
        is_started=True,
        cron_expr="*/5 * * * *",
        remark=None,
        brokerage="ctp",
        weight_precision=0.001,
        long_leverage=1.0,
        short_leverage=1.0,
        algorithm={"method": "SINGLE-MAKER", "params": {}},
        empty_positions_algorithm=None,
        trade_rules={},
        forbidden_symbols=[],
        risk_symbols=[],
        feishu_key=None,
        portfolio_id=1,
        write_empty_record=0,
        account_control_preset=preset,
        account_control_override=override,
    )


def _account_payload() -> dict[str, object]:
    return {
        "name": "ctp-testnet-sim",
        "market": "期货",
        "trade_channel": "ctp",
        "account_config": {
            "broker_id": "9999",
            "investor_id": "test",
            "password": "test",
            "td_front": "tcp://td:1",
            "md_front": "tcp://md:2",
            "app_id": "app",
            "auth_code": "auth",
        },
        "is_started": True,
        "cron_expr": "*/5 * * * *",
        "remark": None,
        "brokerage": "ctp",
        "weight_precision": 0.001,
        "long_leverage": 1.0,
        "short_leverage": 1.0,
        "algorithm": {"method": "SINGLE-MAKER", "params": {}},
        "empty_positions_algorithm": None,
        "trade_rules": {},
        "forbidden_symbols": [],
        "risk_symbols": [],
        "feishu_key": None,
        "portfolio_id": 1,
        "write_empty_record": 0,
        "account_control_preset": "default",
        "account_control_override": {
            "timezone": "Asia/Shanghai",
            "operations": {
                "place_order": {
                    "account": {
                        "per_minute": {"limit": 3, "on_trigger": "wait"},
                        "per_day": {"limit": 30, "on_trigger": "block"},
                        "min_interval_ms": {"limit": 300, "on_trigger": "wait"},
                    }
                }
            },
        },
    }


def _build_app(session: _RouteSession) -> FastAPI:
    app = FastAPI()
    app.include_router(account_routes.router)

    async def _override_get_db() -> AsyncGenerator[_RouteSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_scheduler] = lambda: _Scheduler()
    return app


async def _noop_async(*_args: object, **_kwargs: object) -> None:
    return None


def test_create_account_requires_explicit_account_control_preset() -> None:
    """创建账户时必须显式提供 account_control_preset。"""
    session = _RouteSession()
    payload = _account_payload()
    payload.pop("account_control_preset")

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 422
    assert any(error["loc"][-1] == "account_control_preset" for error in response.json()["detail"])


def test_create_account_rejects_unknown_account_control_preset(monkeypatch) -> None:
    """创建账户时未知 preset 应返回 422。"""
    monkeypatch.setattr(account_crud_routes, "parse_cron_expr", lambda _expr: ["fake-trigger"])
    monkeypatch.setattr(account_crud_routes, "add_record_portfolio_account", _noop_async)
    monkeypatch.setattr(account_crud_routes, "create_job", _noop_async)
    session = _RouteSession()
    payload = _account_payload()
    payload["account_control_preset"] = "missing"

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 422
    assert "未知的账户控制 preset" in response.json()["detail"]
    assert session.account is None


def test_create_account_rejects_incompatible_account_control_preset(monkeypatch) -> None:
    """创建账户时 preset 与渠道不兼容应返回 422。"""
    monkeypatch.setattr(account_crud_routes, "parse_cron_expr", lambda _expr: ["fake-trigger"])
    monkeypatch.setattr(account_crud_routes, "add_record_portfolio_account", _noop_async)
    monkeypatch.setattr(account_crud_routes, "create_job", _noop_async)
    session = _RouteSession()
    payload = _account_payload()
    payload["trade_channel"] = "gm"
    payload["account_config"] = {
        "account_id": "gm-account",
        "token": "token",
        "serv_addr": "127.0.0.1:7001",
    }
    payload["account_control_preset"] = "ctp"

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 422
    assert "不兼容" in response.json()["detail"]
    assert session.account is None


def test_create_account_rejects_invalid_channel_config_with_field_location() -> None:
    """创建接口应在落库前按渠道模型校验，并返回稳定字段位置。"""
    session = _RouteSession()
    payload = _account_payload()
    account_config = payload["account_config"]
    assert isinstance(account_config, dict)
    account_config["td_front"] = "tcp://host"

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"].startswith("account_config.td_front:")
    assert session.account is None


def test_create_account_rejects_unknown_channel_config_field() -> None:
    """渠道模型未声明的字段不能进入账户配置。"""
    session = _RouteSession()
    payload = _account_payload()
    account_config = payload["account_config"]
    assert isinstance(account_config, dict)
    account_config["legacy_option"] = True

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"].startswith("account_config.legacy_option:")
    assert session.account is None


def test_create_account_persists_normalized_channel_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """创建账户只持久化当前模式字段，并写入渠道模型默认值。"""
    monkeypatch.setattr(account_crud_routes, "parse_cron_expr", lambda _expr: ["fake-trigger"])
    monkeypatch.setattr(account_crud_routes, "add_record_portfolio_account", _noop_async)
    monkeypatch.setattr(account_crud_routes, "create_job", _noop_async)
    monkeypatch.setattr(account_crud_routes, "reconcile_china_channel_account", _noop_async)
    session = _RouteSession()
    payload = _account_payload()
    payload["trade_channel"] = "tq"
    payload["brokerage"] = "tq"
    payload["account_config"] = {
        "channel_type": "ctp",
        "account_mode": "sim",
        "tq_username": "user",
        "tq_password": "secret",
        "broker_name": "hidden-broker",
        "account_id": "hidden-account",
        "account_password": "hidden-password",
    }

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 201
    expected = {
        "account_mode": "sim",
        "tq_username": "user",
        "tq_password": "secret",
        "initial_balance": 10_000_000.0,
    }
    assert response.json()["account_config"] == expected
    assert session.account is not None
    assert session.account.account_config == expected


def test_update_account_persists_normalized_channel_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """更新账户与创建使用同一规范化落库路径。"""
    monkeypatch.setattr(account_routes, "_reconcile_account_job", _noop_async)
    monkeypatch.setattr(account_crud_routes, "reconcile_china_channel_account", _noop_async)
    session = _RouteSession(_build_account())

    response = TestClient(_build_app(session)).patch(
        "/account/1",
        json={
            "trade_channel": "tq",
            "account_config": {
                "channel_type": "gm",
                "account_mode": "kq",
                "tq_username": "user",
                "tq_password": "secret",
                "broker_name": "hidden-broker",
                "account_id": "hidden-account",
                "account_password": "hidden-password",
                "initial_balance": 12345,
            },
        },
    )

    assert response.status_code == 200
    expected = {"account_mode": "kq", "tq_username": "user", "tq_password": "secret"}
    assert response.json()["account_config"] == expected
    assert session.account is not None
    assert session.account.account_config == expected


def test_update_account_can_switch_account_control_preset(monkeypatch) -> None:
    """CTP 账户应允许显式切换到 ctp preset。"""
    monkeypatch.setattr(account_routes, "_reconcile_account_job", _noop_async)
    session = _RouteSession(_build_account(trade_channel=TradeChannel.CTP))

    response = TestClient(_build_app(session)).patch(
        "/account/1",
        json={"account_control_preset": "ctp"},
    )

    assert response.status_code == 200
    assert response.json()["account_control_preset"] == "ctp"
    assert session.account is not None
    assert session.account.account_control_preset == "ctp"


def test_update_account_replaces_account_control_override_instead_of_merging(monkeypatch) -> None:
    """PATCH 中 account_control_override 应整字段替换，而不是深度合并。"""
    monkeypatch.setattr(account_routes, "_reconcile_account_job", _noop_async)
    session = _RouteSession(
        _build_account(
            override={
                "timezone": "Asia/Shanghai",
                "operations": {
                    "place_order": {
                        "account": {
                            "per_minute": {"limit": 3, "on_trigger": "wait"},
                            "per_day": {"limit": 30, "on_trigger": "block"},
                            "min_interval_ms": {"limit": 300, "on_trigger": "wait"},
                        }
                    }
                },
            }
        )
    )

    response = TestClient(_build_app(session)).patch(
        "/account/1",
        json={
            "account_control_override": {
                "operations": {
                    "cancel_order": {
                        "account": {
                            "per_day": {"limit": 8, "on_trigger": "block"},
                            "min_interval_ms": {"limit": 900, "on_trigger": "wait"},
                        }
                    }
                },
            }
        },
    )

    assert response.status_code == 200
    override = response.json()["account_control_override"]
    assert override["timezone"] is None
    assert set(override["operations"]) == {"cancel_order"}
    assert override["operations"]["cancel_order"]["account"]["per_day"] == {"limit": 8, "on_trigger": "block"}
    assert override["operations"]["cancel_order"]["account"]["min_interval_ms"] == {
        "limit": 900,
        "on_trigger": "wait",
    }
    assert override["operations"]["cancel_order"]["symbol"] is None
    assert session.account is not None
    assert session.account.account_control_override.timezone is None
    assert session.account.account_control_override.operations == {
        "cancel_order": session.account.account_control_override.operations["cancel_order"]
    }
    assert session.account.account_control_override.operations["cancel_order"].account.per_day.limit == 8
    assert session.account.account_control_override.operations["cancel_order"].account.min_interval_ms.limit == 900


def test_update_account_accepts_null_account_control_override_to_clear(monkeypatch) -> None:
    """PATCH 传 null 应明确清空 override。"""
    monkeypatch.setattr(account_routes, "_reconcile_account_job", _noop_async)
    session = _RouteSession(
        _build_account(
            override={
                "timezone": "Asia/Shanghai",
                "operations": {
                    "place_order": {
                        "account": {
                            "per_minute": {"limit": 3, "on_trigger": "wait"},
                            "min_interval_ms": {"limit": 300, "on_trigger": "wait"},
                        },
                    }
                },
            }
        )
    )

    response = TestClient(_build_app(session)).patch(
        "/account/1",
        json={"account_control_override": None},
    )

    assert response.status_code == 200
    assert response.json()["account_control_override"] is None
    assert session.account is not None
    assert session.account.account_control_override is None

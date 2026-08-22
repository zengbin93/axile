"""首启初始化向导路由测试.

Notes
-----
用仅挂载 ``init.router`` 的最小 FastAPI 应用测试，避开完整应用的 lifespan 与数据库
依赖；这些接口本身也不触达业务数据库。
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import axile.common.config as cfg
from axile.server.api.routes import init as init_module


@pytest.fixture
def client() -> TestClient:
    """仅挂载初始化路由的测试客户端."""
    app = FastAPI()
    app.include_router(init_module.router, prefix="/api/v1")
    return TestClient(app)


class _FakeResp:
    """伪造的 aiohttp 响应上下文."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeResp":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        """模拟成功 HTTP 响应。"""


class _FakeSession:
    """伪造的 aiohttp 会话上下文."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def post(self, _url: str, json: Any = None) -> _FakeResp:  # noqa: A002 - 匹配 aiohttp 签名
        return _FakeResp(self._payload)

    def get(self, _url: str, **_kwargs: Any) -> _FakeResp:
        return _FakeResp(self._payload)


def _patch_aiohttp_response(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    """让走 aiohttp 的连通性测试使用伪造响应，避免真实网络请求."""
    monkeypatch.setattr(
        init_module.aiohttp,
        "ClientSession",
        lambda *_a, **_k: _FakeSession(payload),
    )


def test_init_status_returns_prefill_keys(client: TestClient) -> None:
    """状态接口应返回就绪标志与全部向导字段的预填值."""
    resp = client.get("/api/v1/init/status")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body["values"]) == {
        "sqlalchemy_database_uri",
        "trading_calendar_token",
        "trading_calendar_api",
        "exe_err_feishu_key",
        "environment",
        "app_log_dir",
        "axile_log_rotation",
        "algorithm_modules",
        "algorithm_directories",
    }


def test_test_trading_calendar_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """交易日历测试应校验通用上游契约。"""
    _patch_aiohttp_response(
        monkeypatch,
        [{"exchange": "SSE", "calDate": "2026-08-22", "isOpen": False, "pretradeDate": "2026-08-21"}],
    )

    resp = client.post(
        "/api/v1/init/test-trading-calendar",
        json={"token": "sk_test", "api": "https://calendar.test"},
    )

    assert resp.json()["ok"] is True


def test_test_db_success(client: TestClient, tmp_path: Path) -> None:
    """可连通的 SQLite 地址应返回成功."""
    uri = f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}"

    resp = client.post("/api/v1/init/test-db", json={"uri": uri})

    assert resp.json()["ok"] is True


def test_test_db_failure(client: TestClient) -> None:
    """不可用的数据库地址应返回失败而非抛错."""
    uri = "sqlite+aiosqlite:////nonexistent_dir_xyz/probe.db"

    resp = client.post("/api/v1/init/test-db", json={"uri": uri})

    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_test_feishu_success_status_message(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """飞书返回 StatusMessage=success 时判定推送成功."""
    _patch_aiohttp_response(monkeypatch, {"StatusMessage": "success"})

    resp = client.post("/api/v1/init/test-feishu", json={"key": "abc"})

    assert resp.json()["ok"] is True


def test_test_feishu_success_code_zero(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """飞书返回 code=0 时判定推送成功（兼容新版响应体）."""
    _patch_aiohttp_response(monkeypatch, {"code": 0, "msg": "success"})

    resp = client.post("/api/v1/init/test-feishu", json={"key": "abc"})

    assert resp.json()["ok"] is True


def test_test_feishu_reports_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """飞书返回非零 code 时判定失败，并回传其 msg 供排错."""
    _patch_aiohttp_response(monkeypatch, {"code": 19001, "msg": "invalid access token"})

    resp = client.post("/api/v1/init/test-feishu", json={"key": "bad"})

    body = resp.json()
    assert body["ok"] is False
    assert "invalid access token" in body["message"]


def test_test_feishu_rejects_empty_key(client: TestClient) -> None:
    """key 为空时直接返回失败结果，不发起网络请求."""
    resp = client.post("/api/v1/init/test-feishu", json={"key": "  "})

    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_init_save_rejects_bad_dsn(client: TestClient) -> None:
    """非法数据库地址应返回 422."""
    resp = client.post(
        "/api/v1/init/save",
        json={
            "sqlalchemy_database_uri": "not-a-valid-dsn",
        },
    )

    assert resp.status_code == 422


def test_init_save_rejects_calendar_token_without_api(client: TestClient) -> None:
    """交易日历令牌存在但接口为空时应返回 422。"""
    resp = client.post(
        "/api/v1/init/save",
        json={
            "sqlalchemy_database_uri": "sqlite+aiosqlite:///./axile.db",
            "trading_calendar_token": "token",
        },
    )

    assert resp.status_code == 422


def test_init_save_accepts_empty_calendar(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """交易日历留空应放行并写入 config.toml。"""
    toml_path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)
    monkeypatch.setattr(init_module, "_restart_process", lambda: None)

    resp = client.post(
        "/api/v1/init/save",
        json={
            "sqlalchemy_database_uri": "sqlite+aiosqlite:///./axile.db",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert toml_path.exists()
    written = toml_path.read_text(encoding="utf-8")
    assert 'trading_calendar_api = ""' in written
    assert 'trading_calendar_token = ""' in written
    # 未提供告警 key 时应落盘为空串（默认不推送）。
    assert 'exe_err_feishu_key = ""' in written


def test_init_save_writes_config_and_schedules_restart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """合法请求应写入 config.toml 并调度重启（重启被打桩为无操作）."""
    toml_path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)

    restarted: dict[str, bool] = {}
    monkeypatch.setattr(init_module, "_restart_process", lambda: restarted.setdefault("done", True))

    resp = client.post(
        "/api/v1/init/save",
        json={
            "sqlalchemy_database_uri": "sqlite+aiosqlite:///./axile.db",
            "trading_calendar_api": "http://calendar.test",
            "trading_calendar_token": "tok",
            "exe_err_feishu_key": "bot-key-123",
            "algorithm_modules": ["pkg.a"],
            "algorithm_directories": ["./my_algos"],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert toml_path.exists()
    written = toml_path.read_text(encoding="utf-8")
    assert 'trading_calendar_token = "tok"' in written
    assert 'exe_err_feishu_key = "bot-key-123"' in written
    assert "./my_algos" in written
    assert restarted.get("done") is True

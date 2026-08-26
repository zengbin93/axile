"""首启初始化向导路由测试。"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import axile.common.config as cfg
from axile.server.api.routes import init as init_module


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(init_module.router, prefix="/api/v1")
    return TestClient(app)


class _FakeResp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeResp":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def post(self, _url: str, json: Any = None) -> _FakeResp:  # noqa: A002 - 匹配 aiohttp 签名
        return _FakeResp(self._payload)


def _patch_aiohttp_response(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    monkeypatch.setattr(
        init_module.aiohttp,
        "ClientSession",
        lambda *_args, **_kwargs: _FakeSession(payload),
    )


def test_init_status_returns_prefill_keys(client: TestClient) -> None:
    response = client.get("/api/v1/init/status")

    assert response.status_code == 200
    assert set(response.json()["values"]) == {
        "sqlalchemy_database_uri",
        "exe_err_feishu_key",
        "environment",
        "app_log_dir",
        "axile_log_rotation",
        "algorithm_modules",
        "algorithm_directories",
    }


def test_test_db_success(client: TestClient, tmp_path: Path) -> None:
    uri = f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}"

    response = client.post("/api/v1/init/test-db", json={"uri": uri})

    assert response.json()["ok"] is True


def test_test_db_failure(client: TestClient) -> None:
    response = client.post(
        "/api/v1/init/test-db",
        json={"uri": "sqlite+aiosqlite:////nonexistent_dir_xyz/probe.db"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"StatusMessage": "success"},
        {"code": 0, "msg": "success"},
    ],
)
def test_test_feishu_accepts_success_responses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> None:
    _patch_aiohttp_response(monkeypatch, payload)

    response = client.post("/api/v1/init/test-feishu", json={"key": "abc"})

    assert response.json()["ok"] is True


def test_test_feishu_reports_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_aiohttp_response(monkeypatch, {"code": 19001, "msg": "invalid access token"})

    response = client.post("/api/v1/init/test-feishu", json={"key": "bad"})

    assert response.json()["ok"] is False
    assert "invalid access token" in response.json()["message"]


def test_test_feishu_rejects_empty_key(client: TestClient) -> None:
    response = client.post("/api/v1/init/test-feishu", json={"key": "  "})

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_update_execution_alert_persists_and_updates_runtime_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        '# managed\nsqlalchemy_database_uri = "sqlite+aiosqlite:///./keep.db"\nexe_err_feishu_key = "old-key"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)
    monkeypatch.setattr(cfg.settings, "exe_err_feishu_key", "old-key")
    monkeypatch.setattr(init_module, "_restart_process", lambda: pytest.fail("热更新不应触发重启"))

    response = client.patch(
        "/api/v1/init/execution-alert",
        json={"exe_err_feishu_key": "new-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "执行告警配置已保存并立即生效。"}
    written = toml_path.read_text(encoding="utf-8")
    assert "# managed" in written
    assert 'sqlalchemy_database_uri = "sqlite+aiosqlite:///./keep.db"' in written
    assert 'exe_err_feishu_key = "new-key"' in written
    assert cfg.settings.exe_err_feishu_key == "new-key"


def test_update_execution_alert_accepts_empty_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('exe_err_feishu_key = "old-key"\n', encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)
    monkeypatch.setattr(cfg.settings, "exe_err_feishu_key", "old-key")

    response = client.patch(
        "/api/v1/init/execution-alert",
        json={"exe_err_feishu_key": ""},
    )

    assert response.status_code == 200
    assert 'exe_err_feishu_key = ""' in toml_path.read_text(encoding="utf-8")
    assert cfg.settings.exe_err_feishu_key == ""


def test_update_execution_alert_write_failure_keeps_runtime_value(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('exe_err_feishu_key = "old-key"\n', encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)
    monkeypatch.setattr(cfg.settings, "exe_err_feishu_key", "old-key")

    def _raise_write_error(_key: str, _value: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(init_module, "update_config_toml_value", _raise_write_error)

    response = client.patch(
        "/api/v1/init/execution-alert",
        json={"exe_err_feishu_key": "new-key"},
    )

    assert response.status_code == 500
    assert cfg.settings.exe_err_feishu_key == "old-key"


def test_update_execution_alert_requires_initialized_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", tmp_path / "missing.toml")

    response = client.patch(
        "/api/v1/init/execution-alert",
        json={"exe_err_feishu_key": "new-key"},
    )

    assert response.status_code == 409


def test_init_save_rejects_bad_dsn(client: TestClient) -> None:
    response = client.post(
        "/api/v1/init/save",
        json={"sqlalchemy_database_uri": "not-a-valid-dsn"},
    )

    assert response.status_code == 422


def test_init_save_writes_config_and_schedules_restart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml_path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)
    restarted: dict[str, bool] = {}
    monkeypatch.setattr(init_module, "_restart_process", lambda: restarted.setdefault("done", True))

    response = client.post(
        "/api/v1/init/save",
        json={
            "sqlalchemy_database_uri": "sqlite+aiosqlite:///./axile.db",
            "exe_err_feishu_key": "bot-key-123",
            "algorithm_modules": ["pkg.a"],
            "algorithm_directories": ["./my_algos"],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    written = toml_path.read_text(encoding="utf-8")
    assert 'exe_err_feishu_key = "bot-key-123"' in written
    assert "tushare_token" not in written
    assert "./my_algos" in written
    assert restarted.get("done") is True


def test_calendar_initialization_field_is_removed(client: TestClient) -> None:
    response = client.post(
        "/api/v1/init/save",
        json={"sqlalchemy_database_uri": "sqlite+aiosqlite:///./axile.db", "trading_calendars": []},
    )

    assert response.status_code == 422

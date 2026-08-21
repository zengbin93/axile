"""交易渠道可用性路由测试.

Notes
-----
用仅挂载 ``capabilities.router`` 的最小 FastAPI 应用测试；该接口无副作用、不触达数据库。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.channels import list_channels
from axile.common.trade_channel import TradeChannel
from axile.server import channel_capabilities
from axile.server.api.routes import capabilities as capabilities_module


@pytest.fixture
def client() -> TestClient:
    """仅挂载渠道可用性路由的测试客户端."""
    app = FastAPI()
    app.include_router(capabilities_module.router, prefix="/api/v1")
    return TestClient(app)


def test_channels_reports_all_available_when_deps_present(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """依赖齐备时，每个渠道均标记为可用且无缺失包."""
    monkeypatch.setattr(channel_capabilities.importlib.util, "find_spec", lambda _name: object())

    resp = client.get("/api/v1/capabilities/channels")

    assert resp.status_code == 200
    payload = resp.json()
    # 覆盖全部注册渠道，且顺序对齐注册表定义。
    assert [item["channel"] for item in payload] == [plugin.descriptor.channel for plugin in list_channels()]
    for item in payload:
        assert item["available"] is True
        assert item["missing_packages"] == []
        assert item["label"]
        assert item["defaults"]["execution_timeout"] > 0
        assert "fields" in item["account_form"]
        assert "quantity_kind" in item["units"]
        assert "show_short_leverage" in item["ui"]


def test_channels_reports_missing_dependency_with_install_extra(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """某渠道依赖缺失时，标记不可用并给出缺失包与安装 extra."""
    # 仅 GM 依赖缺失，其余渠道依赖视为已安装。
    gm_pkgs = {"gm"}
    monkeypatch.setattr(
        channel_capabilities.importlib.util,
        "find_spec",
        lambda name: None if name in gm_pkgs else object(),
    )

    resp = client.get("/api/v1/capabilities/channels")

    assert resp.status_code == 200
    by_channel = {item["channel"]: item for item in resp.json()}

    gm = by_channel[TradeChannel.GM.value]
    assert gm["available"] is False
    assert gm["missing_packages"] == ["gm"]
    assert gm["install_extra"] == "gm"

    ctp = by_channel[TradeChannel.CTP.value]
    assert ctp["available"] is True
    assert ctp["missing_packages"] == []

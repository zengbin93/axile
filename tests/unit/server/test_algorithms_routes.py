"""算法注册表查询路由测试.

Notes
-----
用仅挂载 ``algorithms.router`` 的最小 FastAPI 应用测试；该接口只读注册表、无副作用。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.server.api.routes import algorithms as algorithms_module


@pytest.fixture
def client() -> TestClient:
    """仅挂载算法列表路由的测试客户端."""
    app = FastAPI()
    app.include_router(algorithms_module.router, prefix="/api/v1")
    return TestClient(app)


def test_list_algorithms_returns_builtin_metadata(client: TestClient) -> None:
    """返回内置算法元数据，字段与槽位/渠道声明一致，且按名称排序."""
    resp = client.get("/api/v1/algorithms")

    assert resp.status_code == 200
    payload = resp.json()
    by_name = {item["name"]: item for item in payload}

    # 按名称升序。
    assert [item["name"] for item in payload] == sorted(by_name)

    # 全渠道两槽通用算法：channels/slots 均为 None。
    single = by_name["SINGLE-MAKER"]
    assert single["channels"] is None
    assert single["slots"] is None
    assert single["builtin"] is True
    assert single["label"] == "单边挂单"
    assert single["description"]
    assert single["default_params"]
    assert single["params_schema"]["type"] == "object"

    # 两槽都不适用的特种任务：slots 为空列表（非 None）。
    exercise = by_name["CTP_OPTION_EXERCISE"]
    assert exercise["channels"] == ["ctp"]
    assert exercise["slots"] == []

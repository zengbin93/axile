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


@pytest.mark.parametrize(
    ("name", "expected_defaults"),
    [
        (
            "SINGLE-MAKER",
            {
                "price_strategy": "ACTIVE",
                "on_missing_book": "skip",
                "max_wait_seconds": 60,
                "chase_enabled": False,
                "chase_ticks": 1,
                "max_chase_count": 5,
                "chase_interval": 5.0,
            },
        ),
        (
            "TARGET-POS-TASK",
            {
                "price_strategy": "PASSIVE",
                "offset_priority": "昨今",
                "max_wait_seconds": 60,
                "chase_enabled": False,
                "chase_ticks": 1,
                "max_chase_count": 5,
                "chase_interval": 5.0,
            },
        ),
        ("TWAP", {"total_duration": 300, "slices": 10, "price_strategy": "ACTIVE", "max_wait_seconds": 60}),
        (
            "POV",
            {
                "participation_rate": 0.1,
                "interval_seconds": 5.0,
                "max_duration": 600,
                "price_strategy": "ACTIVE",
                "complete_on_timeout": True,
                "max_wait_seconds": 60,
            },
        ),
        (
            "CTP_OPTION_EXERCISE",
            {"action": "exercise", "require_value_check": True, "poll_interval_seconds": 0.5, "max_wait_seconds": 60},
        ),
    ],
)
def test_complete_editor_metadata_preserves_defaults(client, name, expected_defaults):
    item = next(item for item in client.get("/api/v1/algorithms").json() if item["name"] == name)
    assert item["default_params"] == expected_defaults
    assert item["description"]
    fields = item["params_schema"]["properties"]
    assert set(fields) == set(expected_defaults)
    for field in fields.values():
        assert field["title"]
        assert field["description"]
        assert isinstance(field["x-order"], int)
        if "enum" in field:
            assert set(field["x-enum-labels"]) == set(field["enum"])
    assert fields["max_wait_seconds"]["minimum"] == 1
    assert fields["max_wait_seconds"]["maximum"] == 3600


def test_participation_display_scale_does_not_change_wire_constraints(client):
    item = next(item for item in client.get("/api/v1/algorithms").json() if item["name"] == "POV")
    rate = item["params_schema"]["properties"]["participation_rate"]
    assert rate["x-display-scale"] == 100
    assert rate["exclusiveMinimum"] == 0
    assert rate["maximum"] == 1
    assert rate["default"] == 0.1


def test_parameter_controls_keep_wire_contract(client):
    """组件提示覆盖内置算法；快捷值有效且不缩窄参与率精度。"""
    items = client.get("/api/v1/algorithms").json()
    for item in items:
        if item["name"] not in {"TWAP", "POV", "SINGLE-MAKER", "TARGET-POS-TASK", "CTP_OPTION_EXERCISE"}:
            continue
        fields = item["params_schema"]["properties"]
        for field in fields.values():
            if field["type"] in {"integer", "number"}:
                assert field["x-control"] in {"stepper", "numberflow", "presets", "slider"}
            if "x-enum-labels" in field:
                assert field["x-control"] in {"choice", "cards"}
            for preset in field.get("x-presets", []):
                assert field["minimum"] <= preset <= field["maximum"]
    pov = next(item for item in items if item["name"] == "POV")
    rate = pov["params_schema"]["properties"]["participation_rate"]
    assert rate["x-control"] == "numberflow"
    assert rate["x-display-step"] == 1
    assert "x-slider-min" not in rate
    assert "x-slider-max" not in rate
    assert "multipleOf" not in rate

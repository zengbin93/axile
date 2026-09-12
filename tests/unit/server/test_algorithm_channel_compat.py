"""账户级算法 × 渠道订单参数模型的配置期配对校验测试."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from axile.common.order_param_model import OrderParamModel
from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.core.base import ALL_ORDER_PARAM_MODELS, register_algorithm
from axile.server.db.models.account import _check_algorithm_channel_compat


@register_algorithm(
    "TEST-POS-SIDE-ONLY",
    order_param_models=[OrderParamModel.POSITION_SIDE],
    label="仅双向持仓模型测试算法",
)
def _fake_pos_side_only_algorithm(executor, algorithm_input):  # pragma: no cover - 仅注册元数据
    raise NotImplementedError


def test_universal_algorithms_pass_on_builtin_channels() -> None:
    """SINGLE-MAKER/TWAP/POV 声明全模型适配,在三个内置渠道均通过."""
    for channel in (TradeChannel.CTP, TradeChannel.TQ, TradeChannel.GM):
        for method in ("SINGLE-MAKER", "TWAP", "POV"):
            config = {"method": method, "params": {}}
            assert _check_algorithm_channel_compat(config, str(channel), "下单算法") is config


def test_restricted_algorithm_rejected_on_offset_channel() -> None:
    """声明仅 POSITION_SIDE 的算法配对期货(OFFSET)渠道时拒绝."""
    config = {"method": "TEST-POS-SIDE-ONLY", "params": {}}

    with pytest.raises(ValueError, match="未适配渠道 ctp 的订单参数模型"):
        _check_algorithm_channel_compat(config, "ctp", "下单算法")


def test_restricted_algorithm_passes_on_matching_channel() -> None:
    """声明仅 POSITION_SIDE 的算法配对 DIRECTIONAL 渠道仍被拒,UNKNOWN 渠道放行."""
    config = {"method": "TEST-POS-SIDE-ONLY", "params": {}}
    with pytest.raises(ValueError, match="未适配渠道"):
        _check_algorithm_channel_compat(config, "gm", "下单算法")
    # 渠道未注册:交由执行期兜底
    assert _check_algorithm_channel_compat(config, "unregistered-channel", "下单算法") is config


def test_compat_check_passes_through_edge_cases() -> None:
    """空配置、缺 method、未知算法一律放行(与 _validate_algorithm_config 同策略)."""
    assert _check_algorithm_channel_compat(None, "ctp", "下单算法") is None
    assert _check_algorithm_channel_compat({}, "ctp", "下单算法") == {}
    config = {"method": "UNREGISTERED-ALGO", "params": {}}
    assert _check_algorithm_channel_compat(config, "ctp", "下单算法") is config
    registered = {"method": "TEST-POS-SIDE-ONLY", "params": {}}
    assert _check_algorithm_channel_compat(registered, None, "下单算法") is registered


def test_metadata_declares_models() -> None:
    """注册元数据正确记录模型声明."""
    from axile.executor.algorithms.core.base import get_algorithm_metadata

    single_maker = get_algorithm_metadata("SINGLE-MAKER")
    assert single_maker.order_param_models == frozenset(str(model) for model in ALL_ORDER_PARAM_MODELS)
    restricted = get_algorithm_metadata("TEST-POS-SIDE-ONLY")
    assert restricted.order_param_models == frozenset({"position_side"})
    # 未声明的算法(如期货原生 TARGET-POS-TASK)为 None = 全模型,不受本校验约束
    target = get_algorithm_metadata("TARGET-POS-TASK")
    assert target.order_param_models is None


def test_create_account_rejects_incompatible_algorithm_channel_pairing(monkeypatch) -> None:
    """创建账户时算法与渠道参数模型不兼容返回 422."""
    from axile.server.api.routes import account_crud as account_crud_routes
    from tests.unit.server.test_account_control_routes import (
        _account_payload,
        _build_app,
        _noop_async,
        _RouteSession,
    )

    monkeypatch.setattr(account_crud_routes, "parse_cron_expr", lambda _expr: ["fake-trigger"])
    monkeypatch.setattr(account_crud_routes, "add_record_portfolio_account", _noop_async)
    session = _RouteSession()
    payload = _account_payload()
    payload["algorithm"] = {"method": "TEST-POS-SIDE-ONLY", "params": {}}

    response = TestClient(_build_app(session)).post("/account/", json=payload)

    assert response.status_code == 422
    assert "未适配渠道 ctp 的订单参数模型" in response.json()["detail"]
    assert session.account is None


def test_update_account_rejects_incompatible_algorithm_for_next_channel(monkeypatch) -> None:
    """PATCH 只改算法时按生效渠道校验,不兼容返回 422."""
    from axile.server.api.routes import account_crud as account_crud_routes
    from tests.unit.server.test_account_control_routes import (
        _build_account,
        _build_app,
        _noop_async,
        _RouteSession,
        _synchronized_runtime_sync,
    )

    monkeypatch.setattr(account_crud_routes, "enqueue_account_runtime_sync", _noop_async)
    monkeypatch.setattr(account_crud_routes, "reconcile_account_runtime", _synchronized_runtime_sync)
    session = _RouteSession(_build_account())

    response = TestClient(_build_app(session)).patch(
        "/account/1",
        json={"algorithm": {"method": "TEST-POS-SIDE-ONLY", "params": {}}},
    )

    assert response.status_code == 422
    assert "未适配渠道 ctp 的订单参数模型" in response.json()["detail"]


def test_update_account_rejects_current_algorithm_when_switching_channel(monkeypatch) -> None:
    """PATCH 只改渠道时按存量算法校验,不兼容返回 422."""
    from axile.server.api.routes import account_crud as account_crud_routes
    from tests.unit.server.test_account_control_routes import (
        _build_account,
        _build_app,
        _noop_async,
        _RouteSession,
        _synchronized_runtime_sync,
    )

    monkeypatch.setattr(account_crud_routes, "enqueue_account_runtime_sync", _noop_async)
    monkeypatch.setattr(account_crud_routes, "reconcile_account_runtime", _synchronized_runtime_sync)
    account = _build_account()
    account.algorithm = {"method": "TEST-POS-SIDE-ONLY", "params": {}}
    session = _RouteSession(account)

    response = TestClient(_build_app(session)).patch(
        "/account/1",
        json={
            "trade_channel": "gm",
            "account_config": {
                "account_id": "gm-account",
                "token": "token",
                "connection_mode": "service",
                "serv_addr": "127.0.0.1:7001",
            },
        },
    )

    assert response.status_code == 422
    assert "未适配渠道 gm 的订单参数模型" in response.json()["detail"]

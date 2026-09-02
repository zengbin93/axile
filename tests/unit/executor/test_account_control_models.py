"""账户控制配置模型测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.models import (
    AccountControlOperationOverride,
    AccountControlOperationPolicy,
    AccountControlOverride,
)
from axile.executor.account_control.presets import (
    ACCOUNT_CONTROL_PRESETS,
    _build_registry_default_policy,
    ensure_account_control_preset_compatible,
    get_account_control_preset,
    resolve_account_control_policy,
)
from axile.executor.account_control.registry import (
    ensure_default_account_control_registry_bootstrapped,
    reset_default_account_control_registry_for_tests,
)
from axile.server.db.models import Account, AccountCreate, AccountPublic, AccountUpdate


@pytest.fixture(autouse=True)
def _seed_account_control_registry() -> None:
    registry = reset_default_account_control_registry_for_tests()
    ensure_default_account_control_registry_bootstrapped()
    registry.freeze()


def _account_create_payload() -> dict[str, object]:
    return {
        "name": "external-sim",
        "market": "测试市场",
        "trade_channel": TradeChannel("external-demo"),
        "account_config": {"token": "secret"},
        "is_started": True,
        "cron_expr": "*/5 * * * *",
        "remark": None,
        "brokerage": "external",
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
                },
                "query_order": {
                    "account": {
                        "per_day": {"limit": 50, "on_trigger": "block"},
                        "min_interval_ms": {"limit": 100, "on_trigger": "wait"},
                    },
                    "symbol": {
                        "per_minute": {"limit": 5, "on_trigger": "block"},
                    },
                },
            },
        },
    }


def test_account_models_round_trip_account_control_fields() -> None:
    """Account 系列模型应完整保留 preset 与 override。"""
    create_model = AccountCreate.model_validate(_account_create_payload())
    account_model = Account.model_validate(
        {
            **create_model.model_dump(mode="json"),
            "id": 7,
            "created_at": "2026-03-22T12:00:00",
            "updated_at": "2026-03-22T12:00:00",
        }
    )
    public_model = AccountPublic.model_validate(account_model)
    update_model = AccountUpdate.model_validate(
        {
            "account_control_preset": "ctp",
            "account_control_override": public_model.account_control_override.model_dump(mode="json"),
        }
    )

    assert create_model.account_control_preset == "default"
    assert create_model.account_control_override is not None
    assert create_model.account_control_override.timezone == "Asia/Shanghai"
    assert create_model.account_control_override.operations["place_order"].account is not None
    assert create_model.account_control_override.operations["place_order"].account.min_interval_ms.limit == 300
    assert account_model.account_control_override == create_model.account_control_override
    assert public_model.account_control_preset == "default"
    assert public_model.account_control_override == create_model.account_control_override
    assert update_model.account_control_preset == "ctp"
    assert update_model.account_control_override == create_model.account_control_override


def test_account_control_override_rejects_legacy_top_level_operation_fields() -> None:
    """账户控制配置不再接受旧顶层 place/cancel/query 字段。"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AccountControlOverride.model_validate(
            {
                "timezone": "Asia/Shanghai",
                "place_order": {
                    "per_day": {"limit": 1, "on_trigger": "block"},
                },
            }
        )


def test_account_control_operation_models_accept_shorthand_scope_map() -> None:
    """操作级模型应使用显式 account/symbol 作用域映射。"""
    override = AccountControlOperationOverride.model_validate(
        {
            "account": {
                "per_minute": {"limit": 2},
                "min_interval_ms": {"limit": 300},
            }
        }
    )
    policy = AccountControlOperationPolicy.model_validate(
        {
            "account": {
                "per_day": {"limit": 5, "on_trigger": "block"},
            }
        }
    )

    assert override.account is not None
    assert override.account.per_minute is not None
    assert override.account.per_minute.limit == 2
    assert override.account.per_minute.on_trigger is None
    assert override.account.min_interval_ms is not None
    assert override.account.min_interval_ms.limit == 300
    assert override.account.min_interval_ms.on_trigger is None
    assert policy.account.per_day is not None
    assert policy.account.per_day.limit == 5
    assert policy.account.per_day.on_trigger.value == "block"


def test_account_control_presets_register_channels_and_resolve_effective_policy() -> None:
    """系统内置 preset 应仅通过 operations.symbol 解析 symbol 级规则。"""
    assert set(ACCOUNT_CONTROL_PRESETS) == {"default", "ctp"}

    default_preset = get_account_control_preset("default")
    assert default_preset.preset_key == "default"
    assert get_account_control_preset("ctp").preset_key == "ctp"
    assert default_preset.compatible_trade_channels is None
    ensure_account_control_preset_compatible("default", TradeChannel("future-plugin"))

    policy = resolve_account_control_policy(
        "default",
        AccountControlOverride.model_validate(
            {
                "timezone": "UTC",
                "operations": {
                    "place_order": {
                        "account": {
                            "per_minute": {"limit": 2, "on_trigger": "wait"},
                            "min_interval_ms": {"limit": 600, "on_trigger": "wait"},
                        }
                    },
                    "query_order": {
                        "symbol": {
                            "per_day": {"limit": 9, "on_trigger": "block"},
                            "min_interval_ms": {"limit": 1200, "on_trigger": "wait"},
                        }
                    },
                },
            }
        ),
    )

    assert policy.preset_key == "default"
    assert policy.timezone == "UTC"
    assert policy.operations["place_order"].account.per_minute.limit == 2
    assert policy.operations["place_order"].account.per_day.limit == 500
    assert policy.operations["place_order"].account.min_interval_ms.limit == 600
    assert policy.operations["place_order"].symbol is not None
    assert policy.operations["place_order"].symbol.per_minute.limit == 10
    assert policy.operations["query_order"].symbol is not None
    assert policy.operations["query_order"].symbol.per_day.limit == 9
    assert policy.operations["query_order"].symbol.min_interval_ms.limit == 1200


def test_registry_default_policy_only_keeps_shape_without_numeric_defaults() -> None:
    """registry 默认策略不应隐式补 symbol 级骨架。"""
    policy = _build_registry_default_policy()

    assert policy.operations["place_order"].account.per_minute is None
    assert policy.operations["place_order"].account.per_day is None
    assert policy.operations["place_order"].account.min_interval_ms is None
    assert policy.operations["place_order"].symbol is None
    assert policy.operations["query_account"].account.per_minute is None
    assert policy.operations["query_account"].account.per_day is None
    assert policy.operations["query_account"].account.min_interval_ms is None
    assert policy.operations["query_account"].symbol is None
    assert policy.groups["ctp_td_global"].per_minute is None
    assert policy.groups["ctp_td_global"].per_day is None
    assert policy.groups["ctp_td_global"].min_interval_ms is None


def test_ctp_account_control_preset_uses_ctp_specific_limits() -> None:
    """CTP preset 应声明渠道兼容性与专属限流阈值。"""
    preset = get_account_control_preset("ctp")
    policy = resolve_account_control_policy("ctp")

    assert preset.preset_key == "ctp"
    assert preset.compatible_trade_channels == {TradeChannel.CTP}
    assert preset.policy.timezone == "Asia/Shanghai"
    assert preset.policy.operations["query_order"].account.per_minute.limit == 60
    assert preset.policy.operations["query_order"].account.per_day.limit == 2000
    assert preset.policy.operations["query_order"].account.min_interval_ms.limit == 1500
    assert policy.operations["query_order"].priority == 100
    assert preset.policy.operations["place_order"].account.per_minute.limit == 30
    assert preset.policy.operations["place_order"].account.per_day.limit == 500
    assert preset.policy.operations["place_order"].account.min_interval_ms.limit == 500
    assert policy.operations["place_order"].priority == 10
    assert preset.policy.operations["cancel_order"].account.per_minute.limit == 60
    assert preset.policy.operations["cancel_order"].account.per_day.limit == 400
    assert preset.policy.operations["cancel_order"].account.min_interval_ms.limit == 200
    assert policy.operations["cancel_order"].priority == 0
    assert "insert_order" not in policy.operations
    assert policy.operation_groups["place_order"] == {"ctp_td_global"}
    assert policy.operation_groups["query_account"] == {"ctp_td_global"}
    assert policy.operations["cancel_order_ctp"].priority == 0
    assert preset.policy.groups["ctp_td_global"].min_interval_ms.limit == 1500

    ensure_account_control_preset_compatible("ctp", TradeChannel.CTP)
    with pytest.raises(ValueError, match="不兼容"):
        ensure_account_control_preset_compatible("ctp", TradeChannel("external-demo"))


def test_ctp_option_operation_keeps_account_override() -> None:
    """CTP 期权操作仍允许账户覆盖业务限额。"""
    policy = resolve_account_control_policy(
        "ctp",
        AccountControlOverride.model_validate(
            {
                "operations": {
                    "option_self_close": {
                        "account": {"per_day": {"limit": 10, "on_trigger": "block"}},
                    }
                }
            }
        ),
    )

    assert policy.operations["option_self_close"].account.per_day is not None
    assert policy.operations["option_self_close"].account.per_day.limit == 10


def test_default_query_operation_keeps_account_override() -> None:
    """通用 preset 的查询操作不受 CTP 专属分组影响。"""
    policy = resolve_account_control_policy(
        "default",
        AccountControlOverride.model_validate(
            {
                "operations": {
                    "query_account": {
                        "account": {"per_day": {"limit": 7, "on_trigger": "block"}},
                    }
                }
            }
        ),
    )

    assert policy.operations["query_account"].account.per_day is not None
    assert policy.operations["query_account"].account.per_day.limit == 7
    assert "query_account" not in policy.operation_groups


def test_default_account_control_preset_uses_generic_min_intervals() -> None:
    """default preset 应提供通用覆盖值。"""
    preset = get_account_control_preset("default")

    assert preset.policy.operations["query_order"].account.min_interval_ms.limit == 100
    assert preset.policy.operations["place_order"].account.min_interval_ms.limit == 300
    assert preset.policy.operations["cancel_order"].account.min_interval_ms.limit == 200


def test_account_control_override_rejects_invalid_values() -> None:
    """未知 preset、非法时区、未注册 key 和非法规则值都应快速失败。"""
    with pytest.raises(ValueError, match="未知"):
        get_account_control_preset("missing")

    with pytest.raises(ValidationError, match="timezone"):
        AccountControlOverride.model_validate({"timezone": "Mars/Olympus"})

    with pytest.raises(ValidationError, match="未注册的 operation key"):
        AccountControlOverride.model_validate({"operations": {"missing": {"account": {}}}})

    with pytest.raises(ValidationError, match="未注册的 group key"):
        AccountControlOverride.model_validate({"groups": {"missing_group": {}}})

    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        AccountControlOverride.model_validate(
            {
                "operations": {
                    "place_order": {
                        "account": {"per_minute": {"limit": -1, "on_trigger": "wait"}},
                    }
                }
            }
        )

    with pytest.raises(ValidationError, match="min_interval_ms"):
        AccountControlOverride.model_validate(
            {
                "operations": {
                    "place_order": {
                        "account": {"min_interval_ms": {"limit": 0, "on_trigger": "wait"}},
                    }
                }
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AccountControlOverride.model_validate({"symbol_overrides": {}})


def test_account_control_override_rejects_legacy_disable_switch() -> None:
    """账户控制不接受旧版 enabled 开关。"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AccountControlOverride.model_validate({"enabled": False})


def test_account_control_rule_override_unlimited_resolves_to_no_rule() -> None:
    """额度类规则允许显式 unlimited，解析后不启用该规则。"""
    policy = resolve_account_control_policy(
        "default",
        AccountControlOverride.model_validate(
            {
                "operations": {
                    "place_order": {
                        "account": {
                            "per_minute": {"unlimited": True},
                            "per_day": {"unlimited": True},
                        }
                    }
                }
            }
        ),
    )

    place_order_account = policy.operations["place_order"].account
    assert place_order_account.per_minute is None
    assert place_order_account.per_day is None
    # 未覆盖的规则保持预设值
    assert place_order_account.min_interval_ms is not None
    assert place_order_account.min_interval_ms.limit == 300


def test_account_control_rule_override_unlimited_rejects_mixed_and_interval() -> None:
    """unlimited 与 limit/on_trigger 互斥，且 min_interval_ms 不允许解除。"""
    with pytest.raises(ValidationError, match="互斥"):
        AccountControlOverride.model_validate(
            {"operations": {"place_order": {"account": {"per_minute": {"limit": 5, "unlimited": True}}}}}
        )

    with pytest.raises(ValidationError, match="不允许设置为不限制"):
        AccountControlOverride.model_validate(
            {"operations": {"place_order": {"account": {"min_interval_ms": {"unlimited": True}}}}}
        )

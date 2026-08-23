"""统一输入与开放渠道配置校验测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import Field, ValidationError

from axile.channels import (
    AlgorithmReference,
    ChannelAccountForm,
    ChannelDefaults,
    ChannelDescriptor,
    ChannelLeverage,
    ChannelPlugin,
    ChannelPortfolioPreset,
    list_channels,
    register_channel,
    registry,
)
from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.defaults.ctp_target_pos_task.impl import CTPTargetPosTaskParams
from axile.executor.models.unified_input import GMAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_input_accounts import BaseAccountConfig, CTPAccountConfig


def _ctp_payload() -> dict[str, object]:
    return {
        "channel_type": "ctp",
        "account_config": {
            "broker_id": "9999",
            "investor_id": "000001",
            "password": "secret",
            "td_front": "tcp://td:10001",
            "md_front": "tcp://md:10002",
            "app_id": "app-id",
            "auth_code": "auth-code",
        },
        "curr_target": {"rb2505": 1.0},
    }


def test_from_dict_requires_explicit_channel() -> None:
    payload = _ctp_payload()
    payload.pop("channel_type")

    with pytest.raises(ValueError, match="必须明确指定 channel_type"):
        UnifiedStandardInput.from_dict(payload)


def test_ctp_input_uses_plugin_config_model_and_defaults() -> None:
    standard_input = UnifiedStandardInput.from_dict(_ctp_payload())

    assert standard_input.channel_type == TradeChannel.CTP
    assert isinstance(standard_input.account_config, CTPAccountConfig)
    assert standard_input.algorithm == {"method": "TARGET-POS-TASK", "params": {}}


def test_direct_model_validation_also_uses_plugin_config_model() -> None:
    standard_input = UnifiedStandardInput.model_validate(_ctp_payload())

    assert isinstance(standard_input.account_config, CTPAccountConfig)
    assert standard_input.algorithm["method"] == "TARGET-POS-TASK"


def test_gm_config_requires_explicit_connection_mode() -> None:
    payload = {
        "channel_type": "gm",
        "account_config": {
            "account_id": "account-id",
            "token": "token",
            "terminal_path": "C:\\GoldMiner3",
            "serv_addr": "127.0.0.1:7001",
        },
        "curr_target": {"SHSE.600000": 1.0},
    }

    with pytest.raises(ValidationError, match="connection_mode"):
        UnifiedStandardInput.from_dict(payload)


def test_gm_config_serializes_only_active_connection_target() -> None:
    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": "gm",
            "account_config": {
                "connection_mode": "service",
                "account_id": "account-id",
                "token": "token",
                "terminal_path": "C:\\ignored",
                "serv_addr": "127.0.0.1:7001",
            },
            "curr_target": {"SHSE.600000": 1.0},
        }
    )

    assert isinstance(standard_input.account_config, GMAccountConfig)
    assert standard_input.to_dict()["account_config"] == {
        "channel_type": "gm",
        "connection_mode": "service",
        "account_id": "account-id",
        "token": "token",
        "serv_addr": "127.0.0.1:7001",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("td_front", "tcp://host"),
        ("md_front", "http://host:10002"),
    ],
)
def test_ctp_config_rejects_invalid_fronts(field: str, value: str) -> None:
    payload = _ctp_payload()
    account_config = payload["account_config"]
    assert isinstance(account_config, dict)
    account_config[field] = value

    with pytest.raises(ValidationError):
        UnifiedStandardInput.model_validate(payload)


@pytest.mark.parametrize("value", ["123213", "tcp://127.0.0.1:7001", "127.0.0.1:70000"])
def test_gm_config_rejects_invalid_service_address(value: str) -> None:
    with pytest.raises(ValidationError):
        GMAccountConfig.model_validate(
            {"connection_mode": "service", "account_id": "id", "token": "token", "serv_addr": value}
        )


def test_gm_config_rejects_non_windows_terminal_path() -> None:
    with pytest.raises(ValidationError, match="Windows"):
        GMAccountConfig.model_validate(
            {"connection_mode": "terminal", "account_id": "id", "token": "token", "terminal_path": "/tmp/gm"}
        )


def test_symbol_algorithm_and_extra_round_trip() -> None:
    payload = {
        **_ctp_payload(),
        "algorithm": {"method": "TARGET-POS-TASK", "params": {"max_wait_seconds": 5}},
        "symbol_algorithms": {"rb2505": {"params": {"max_wait_seconds": 9}}},
        "extra": {"trace": "demo"},
    }
    standard_input = UnifiedStandardInput.from_dict(payload)

    assert standard_input.get_symbol_algorithm("rb2505") == {
        "method": "TARGET-POS-TASK",
        "params": {"max_wait_seconds": 9},
    }
    assert standard_input.to_dict()["extra"] == {"trace": "demo"}


def test_algorithm_params_are_parsed_with_registered_schema() -> None:
    standard_input = UnifiedStandardInput.from_dict(
        {
            **_ctp_payload(),
            "algorithm": {"method": "TARGET-POS-TASK", "params": {"max_wait_seconds": 5}},
        }
    )

    standard_input.parse_algorithm_params("TARGET-POS-TASK")

    assert isinstance(standard_input.algorithm["params"], CTPTargetPosTaskParams)
    assert standard_input.algorithm["params"].max_wait_seconds == 5


def test_external_plugin_controls_unknown_channel_config_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExternalConfig(BaseAccountConfig):
        account_ref: str = Field(min_length=1)

    class _NoEntryPoints(list[object]):
        def select(self, **_kwargs: object) -> _NoEntryPoints:
            return self

    def target_transform(config: dict[str, float], frame: pd.DataFrame) -> pd.DataFrame:
        del config
        return frame

    monkeypatch.setattr(registry.metadata, "entry_points", lambda: _NoEntryPoints())
    registry._reset_registry_for_tests()
    list_channels()
    register_channel(
        ChannelPlugin(
            descriptor=ChannelDescriptor(
                channel="external-demo",
                label="External Demo",
                description="测试外部渠道",
                icon="plug",
                market="demo",
                currency="USD",
                defaults=ChannelDefaults(
                    long_leverage=1,
                    short_leverage=1,
                    execution_timeout=30,
                    trade_algorithm=AlgorithmReference(method="SINGLE-MAKER", params={}),
                ),
                leverage=ChannelLeverage(min=0, max=2, step=0.1),
                account_form=ChannelAccountForm(),
                portfolio=ChannelPortfolioPreset(market_label="Demo", example_symbols=("X",)),
            ),
            account_config_model=ExternalConfig,
            create_executor=lambda config: SimpleNamespace(config=config),
            target_transform=target_transform,
        )
    )
    try:
        standard_input = UnifiedStandardInput.from_dict(
            {
                "channel_type": "external-demo",
                "account_config": {"account_ref": "A-1"},
                "curr_target": {"X": 1.0},
            }
        )
        assert isinstance(standard_input.account_config, ExternalConfig)
        assert standard_input.channel_type == "external-demo"
    finally:
        registry._reset_registry_for_tests()

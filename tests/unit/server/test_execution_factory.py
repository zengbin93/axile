"""执行器插件工厂测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from axile.channels import (
    AlgorithmReference,
    ChannelAccountForm,
    ChannelDefaults,
    ChannelDescriptor,
    ChannelLeverage,
    ChannelPlugin,
    list_channels,
    register_channel,
    registry,
)
from axile.executor.models.unified_input_accounts import BaseAccountConfig
from axile.server.execution.factory import create_executor_instance


class _Config(BaseAccountConfig):
    """工厂测试账户配置。"""

    key: str


def _transform(_config: dict[str, float], frame: pd.DataFrame) -> pd.DataFrame:
    return frame


def _plugin() -> ChannelPlugin:
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel="factory-demo",
            label="Factory Demo",
            description="测试执行器工厂",
            icon="plug",
            market="demo",
            currency="USD",
            defaults=ChannelDefaults(
                long_leverage=1,
                short_leverage=1,
                execution_timeout=60,
                trade_algorithm=AlgorithmReference(method="SINGLE-MAKER", params={}),
            ),
            leverage=ChannelLeverage(min=0, max=2, step=0.1),
            account_form=ChannelAccountForm(),
        ),
        account_config_model=_Config,
        create_executor=lambda config: SimpleNamespace(config=config),
        target_transform=_transform,
    )


def test_create_executor_instance_uses_registered_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoEntryPoints(list[object]):
        def select(self, **_kwargs: object) -> _NoEntryPoints:
            return self

    monkeypatch.setattr(registry.metadata, "entry_points", lambda: _NoEntryPoints())
    registry._reset_registry_for_tests()
    list_channels()
    register_channel(_plugin())
    try:
        executor = create_executor_instance(
            SimpleNamespace(trade_channel="factory-demo", account_config={"key": "secret"})
        )
        assert isinstance(executor.config, _Config)
        assert executor.config.channel_type == "factory-demo"
    finally:
        registry._reset_registry_for_tests()


def test_create_executor_instance_rejects_unregistered_channel() -> None:
    with pytest.raises(ValueError, match="未注册交易渠道: missing-channel"):
        create_executor_instance(SimpleNamespace(trade_channel="missing-channel", account_config={}))

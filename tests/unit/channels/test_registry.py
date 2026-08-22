"""开放交易渠道插件注册表测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import Field, ValidationError
from sqlalchemy import Text

from axile.channels import (
    AlgorithmReference,
    ChannelAccountField,
    ChannelAccountForm,
    ChannelDefaults,
    ChannelDescriptor,
    ChannelLeverage,
    ChannelPlugin,
    ChannelUi,
    ChannelUnits,
    DuplicateChannelError,
    get_channel,
    list_channels,
    register_channel,
    registry,
)
from axile.executor.abstract_executor.capability import AbstractExecutorCapabilityMixin
from axile.executor.models.unified_input_accounts import BaseAccountConfig
from axile.server.api.routes.capabilities import list_channel_capabilities
from axile.server.db.models import Account, AccountControlEvent, AccountCreate, ExecutionEvent
from axile.server.execution.dispatch import ExecutionBackendKind, resolve_execution_backend_kind
from axile.server.execution.execution_algorithms import resolve_account_leverages
from axile.server.execution.factory import create_executor_instance


class DemoAccountConfig(BaseAccountConfig):
    """测试插件账户配置。"""

    token: str = Field(min_length=1)


def _plugin(
    channel: str = "vendor-demo",
    *,
    required_modules: tuple[str, ...] = (),
    max_parallel_symbols: int = 4,
) -> ChannelPlugin:
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel=channel,
            label="Vendor Demo",
            description="用于验证开放渠道边界",
            icon="plug",
            market="demo",
            currency="USD",
            units=ChannelUnits(
                quantity_kind="base_asset",
                quantity_label="资产",
                quantity_max_decimals=8,
                price_label="USD",
            ),
            ui=ChannelUi(
                account_connect_lead="填写供应商令牌。",
                leverage_note="支持双向目标仓位",
            ),
            defaults=ChannelDefaults(
                long_leverage=2,
                short_leverage=1,
                execution_timeout=90,
                trade_algorithm=AlgorithmReference(method="DEMO", params={"pace": 2}),
                empty_positions_algorithm=AlgorithmReference(method="DEMO-EMPTY", params={}),
            ),
            leverage=ChannelLeverage(min=0, max=10, step=0.5),
            account_form=ChannelAccountForm(
                fields=(ChannelAccountField(name="token", label="Token", input="password"),)
            ),
        ),
        account_config_model=DemoAccountConfig,
        create_executor=lambda config: SimpleNamespace(config=config),
        execution_backend="process",
        required_modules=required_modules,
        max_parallel_symbols=max_parallel_symbols,
    )


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch):
    """隔离每个测试的入口点与进程内注册状态。"""

    class _NoEntryPoints(list[object]):
        def select(self, **_kwargs: object) -> _NoEntryPoints:
            return self

    monkeypatch.setattr(registry.metadata, "entry_points", lambda: _NoEntryPoints())
    registry._reset_registry_for_tests()
    yield
    registry._reset_registry_for_tests()


def test_builtin_channels_have_stable_order_and_descriptor_shape() -> None:
    plugins = list_channels()

    assert [plugin.descriptor.channel for plugin in plugins] == ["ctp", "gm"]
    assert plugins[0].descriptor.account_form.fields
    assert plugins[0].descriptor.defaults.trade_algorithm.method == "TARGET-POS-TASK"
    assert plugins[0].descriptor.units.quantity_label == "手"
    assert plugins[1].descriptor.units.quantity_label == "股"
    assert plugins[1].descriptor.ui.show_short_leverage is False


def test_duplicate_channel_registration_fails_clearly() -> None:
    list_channels()

    with pytest.raises(DuplicateChannelError, match="重复注册"):
        register_channel(_plugin("ctp"))


def test_entry_point_is_loaded_once_and_appended_after_builtins(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[str] = []

    class _EntryPoint:
        name = "vendor"
        value = "vendor.plugin:channel"

        def load(self) -> ChannelPlugin:
            loads.append(self.name)
            return _plugin()

    class _EntryPoints(list[_EntryPoint]):
        def select(self, **kwargs: object) -> _EntryPoints:
            return self if kwargs == {"group": "axile.channels"} else _EntryPoints()

    monkeypatch.setattr(registry.metadata, "entry_points", lambda: _EntryPoints([_EntryPoint()]))

    assert get_channel("vendor-demo").descriptor.label == "Vendor Demo"
    assert list_channels()[-1].descriptor.channel == "vendor-demo"
    assert loads == ["vendor"]


def test_factory_validates_plugin_config_before_creating_executor() -> None:
    list_channels()
    register_channel(_plugin())
    account = SimpleNamespace(trade_channel="vendor-demo", account_config={"token": "secret"})

    executor = create_executor_instance(account)

    assert isinstance(executor.config, DemoAccountConfig)
    assert executor.config.channel_type == "vendor-demo"

    with pytest.raises(ValidationError):
        create_executor_instance(SimpleNamespace(trade_channel="vendor-demo", account_config={"token": ""}))


def test_capabilities_expose_descriptor_and_runtime_availability() -> None:
    list_channels()
    register_channel(_plugin(required_modules=("module_that_does_not_exist_for_axile_test",)))

    capability = next(item for item in list_channel_capabilities() if item.channel == "vendor-demo")

    assert capability.label == "Vendor Demo"
    assert capability.currency == "USD"
    assert capability.units.quantity_kind == "base_asset"
    assert capability.units.quantity_max_decimals == 8
    assert capability.ui.account_connect_lead == "填写供应商令牌。"
    assert capability.defaults.execution_timeout == 90
    assert capability.account_form.fields[0].name == "token"
    assert capability.available is False
    assert capability.missing_packages == ["module_that_does_not_exist_for_axile_test"]


def test_runtime_policies_resolve_from_plugin() -> None:
    list_channels()
    register_channel(_plugin())
    account = SimpleNamespace(
        trade_channel="vendor-demo",
        market="demo",
        long_leverage=None,
        short_leverage=None,
    )

    assert resolve_execution_backend_kind("vendor-demo") == ExecutionBackendKind.PROCESS
    assert resolve_account_leverages(account) == (2.0, 1.0)


def test_db_models_accept_arbitrary_channel_strings_and_use_text_columns() -> None:
    account = AccountCreate.model_validate(
        {
            "name": "demo",
            "market": "demo",
            "trade_channel": "vendor-demo",
            "account_control_preset": "default",
            "account_control_override": None,
            "account_config": {"token": "secret"},
            "is_started": False,
            "cron_expr": "",
            "remark": None,
            "brokerage": "vendor",
            "weight_precision": 0.01,
            "long_leverage": None,
            "short_leverage": None,
            "algorithm": {"method": "DEMO", "params": {}},
            "empty_positions_algorithm": None,
            "trade_rules": None,
            "forbidden_symbols": None,
            "risk_symbols": None,
            "feishu_key": None,
            "portfolio_id": None,
            "write_empty_record": None,
        }
    )

    assert account.trade_channel == "vendor-demo"
    assert isinstance(Account.__table__.c.trade_channel.type, Text)
    assert isinstance(ExecutionEvent.__table__.c.channel.type, Text)
    assert isinstance(AccountControlEvent.__table__.c.channel.type, Text)


def test_executor_parallel_limit_comes_from_plugin() -> None:
    list_channels()
    register_channel(_plugin(max_parallel_symbols=7))

    class _Executor(AbstractExecutorCapabilityMixin):
        channel_type = "vendor-demo"

    executor = _Executor()
    assert executor._supports_parallel_symbol_dispatch() is True
    assert executor._max_parallel_symbol_workers() == 7

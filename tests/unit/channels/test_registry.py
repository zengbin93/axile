"""开放交易渠道插件注册表测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import Field, ValidationError
from sqlalchemy import Text

from axile.channels import (
    AlgorithmReference,
    ChannelAccountField,
    ChannelAccountFieldClipboard,
    ChannelAccountFieldConstraints,
    ChannelAccountForm,
    ChannelCalendar,
    ChannelDefaults,
    ChannelDescriptor,
    ChannelEndpointConstraints,
    ChannelLeverage,
    ChannelPlugin,
    ChannelPortfolioPreset,
    ChannelSchedule,
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


def _target_transform(config: dict[str, float], frame: pd.DataFrame) -> pd.DataFrame:
    transformed = frame.copy()
    transformed["contribution"] = transformed["weight"] * transformed["strategy"].map(config)
    return transformed


def _plugin(
    channel: str = "vendor-demo",
    *,
    required_modules: tuple[str, ...] = (),
    max_parallel_symbols: int = 4,
    calendar: ChannelCalendar | None = None,
) -> ChannelPlugin:
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel=channel,
            label="Vendor Demo",
            description="用于验证开放渠道边界",
            icon="plug",
            market="demo",
            schedule=ChannelSchedule(kind="continuous"),
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
                fields=(ChannelAccountField(name="token", label="Token", kind="secret", width="full"),)
            ),
            calendar=calendar,
            portfolio=ChannelPortfolioPreset(market_label="Vendor", example_symbols=("DEMO",)),
        ),
        account_config_model=DemoAccountConfig,
        create_executor=lambda config: SimpleNamespace(config=config),
        target_transform=_target_transform,
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

    assert [plugin.descriptor.channel for plugin in plugins] == ["ctp", "gm", "tq"]
    assert [plugin.descriptor.schedule.kind for plugin in plugins] == ["cn_futures", "cn_stock", "cn_futures"]
    assert plugins[0].descriptor.schedule.night == plugins[2].descriptor.schedule.night
    assert plugins[0].descriptor.schedule.night is not None
    assert plugins[0].descriptor.schedule.night.close == ("02:30",)
    assert plugins[0].descriptor.schedule.night.m15[0] == "21:15"
    assert plugins[0].descriptor.schedule.night.m15[-1] == "02:30"
    assert plugins[1].descriptor.schedule.night is None
    assert plugins[0].descriptor.account_form.fields
    assert plugins[0].descriptor.defaults.trade_algorithm.method == "TARGET-POS-TASK"
    assert plugins[0].descriptor.portfolio.market_label == "期货"
    assert plugins[0].descriptor.portfolio.example_symbols == ("rb2610", "ag2612")
    assert plugins[0].descriptor.units.quantity_label == "手"
    assert plugins[1].descriptor.units.quantity_label == "股"
    assert plugins[1].descriptor.ui.show_short_leverage is False
    assert plugins[2].descriptor.defaults.trade_algorithm.method == "TARGET-POS-TASK"
    assert plugins[1].descriptor.portfolio.market_label == "A股"
    assert plugins[1].descriptor.portfolio.example_symbols == ("600000.SH", "000001.SZ")
    assert [plugin.descriptor.calendar.calendar_id for plugin in plugins] == ["china", "ashare", "china"]
    assert plugins[2].descriptor.portfolio == plugins[0].descriptor.portfolio
    assert [plugin.max_parallel_symbols for plugin in plugins] == [10, 10, 10]
    assert plugins[2].descriptor.account_form.fields[0].default is None


def test_channel_descriptor_requires_schedule_kind() -> None:
    """插件必须显式声明调度类型，禁止未知渠道静默套用默认规则。"""
    payload = _plugin().descriptor.model_dump()
    payload.pop("schedule")

    with pytest.raises(ValidationError, match="schedule"):
        ChannelDescriptor.model_validate(payload)


def test_account_field_rejects_legacy_input_contract() -> None:
    """渠道字段必须完整声明新语义，不接受旧 input 协议或隐式默认值."""
    with pytest.raises(ValidationError):
        ChannelAccountField.model_validate({"name": "token", "label": "Token", "input": "password"})
    with pytest.raises(ValidationError):
        ChannelAccountField.model_validate({"name": "token", "label": "Token"})


def test_account_field_constraints_match_semantic_kind() -> None:
    """约束只能声明在对应语义字段上，协议规则必须自洽。"""
    constraints = ChannelAccountFieldConstraints(
        endpoint=ChannelEndpointConstraints(
            scheme="required",
            allowed_schemes=("tcp",),
            port="required",
        )
    )
    field = ChannelAccountField(
        name="front",
        label="前置",
        kind="endpoint",
        width="full",
        constraints=constraints,
    )

    assert field.model_dump()["constraints"]["endpoint"] == {
        "scheme": "required",
        "allowed_schemes": ("tcp",),
        "port": "required",
        "allow_path": False,
    }
    with pytest.raises(ValidationError):
        ChannelAccountField(
            name="token",
            label="Token",
            kind="secret",
            width="full",
            constraints=constraints,
        )
    with pytest.raises(ValidationError, match="clipboard"):
        ChannelAccountField(
            name="token",
            label="Token",
            kind="secret",
            width="full",
            clipboard=ChannelAccountFieldClipboard(role="rpc"),
        )
    with pytest.raises(ValidationError, match="展示模式"):
        ChannelAccountField(
            name="token",
            label="Token",
            kind="secret",
            width="full",
            presentation="conditional_reveal",
        )


def test_builtin_account_contracts_expose_validation_constraints() -> None:
    """内置渠道描述输出与执行器实际确定性要求一致。"""
    plugins = {plugin.descriptor.channel: plugin for plugin in list_channels()}
    ctp_fields = {field.name: field for field in plugins["ctp"].descriptor.account_form.fields}
    gm_fields = {field.name: field for field in plugins["gm"].descriptor.account_form.fields}
    tq_fields = {field.name: field for field in plugins["tq"].descriptor.account_form.fields}

    assert all(
        ctp_fields[name].required
        for name in ("broker_id", "investor_id", "password", "td_front", "md_front", "app_id", "auth_code")
    )
    assert ctp_fields["td_front"].constraints.endpoint.allowed_schemes == ("tcp",)
    assert ctp_fields["md_front"].constraints.endpoint.port == "required"
    assert gm_fields["serv_addr"].constraints.endpoint.scheme == "forbidden"
    assert gm_fields["connection_mode"].presentation == "conditional_reveal"
    assert gm_fields["connection_mode"].options[1].description.startswith("Axile 连接")
    assert tq_fields["initial_balance"].constraints.number.gt == 0
    assert tq_fields["account_mode"].presentation == "conditional_reveal"
    assert tq_fields["account_mode"].default is None


def test_duplicate_channel_registration_fails_clearly() -> None:
    list_channels()

    with pytest.raises(DuplicateChannelError, match="重复注册"):
        register_channel(_plugin("ctp"))


def test_plugins_can_declare_same_calendar_without_cross_plugin_comparison() -> None:
    list_channels()
    register_channel(_plugin("vendor-one", calendar=ChannelCalendar(calendar_id="vendor", label="Vendor Calendar")))
    register_channel(_plugin("vendor-two", calendar=ChannelCalendar(calendar_id="vendor", label="Other Label")))

    assert get_channel("vendor-one").descriptor.calendar.calendar_id == "vendor"
    assert get_channel("vendor-two").descriptor.calendar.label == "Other Label"


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
    assert capability.portfolio.market_label == "Vendor"
    assert capability.portfolio.example_symbols == ("DEMO",)
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


def test_builtin_target_transforms_are_available_from_registry() -> None:
    ctp_frame = pd.DataFrame([{"strategy": "alpha", "symbol": "rb", "weight": 0.5}])
    gm_frame = pd.DataFrame([{"strategy": "alpha", "symbol": "600000.SH", "weight": 0.5}])

    ctp_result = get_channel("ctp").target_transform({"alpha": 0.4}, ctp_frame)
    gm_result = get_channel("gm").target_transform({"alpha": 0.4}, gm_frame)
    tq_frame = pd.DataFrame([{"strategy": "alpha", "symbol": "rb2610", "weight": 0.5}])
    tq_result = get_channel("tq").target_transform({"alpha": 0.4}, tq_frame)

    assert ctp_result.to_dict("records") == [
        {"strategy": "alpha", "symbol": "rb", "weight": 0.5, "contribution": pytest.approx(0.2)}
    ]
    assert gm_result.to_dict("records") == [
        {
            "strategy": "alpha",
            "symbol": "600000.SH",
            "weight": 0.5,
            "contribution": pytest.approx(0.2),
        }
    ]
    assert tq_result.to_dict("records") == [
        {"strategy": "alpha", "symbol": "rb2610", "weight": 0.5, "contribution": pytest.approx(0.2)}
    ]
    assert "contribution" not in tq_frame.columns

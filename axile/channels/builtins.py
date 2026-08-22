"""声明公开包内置的 CTP 与 GM 渠道插件."""

from __future__ import annotations

from axile.channels.contracts import (
    AlgorithmReference,
    ChannelAccountField,
    ChannelAccountForm,
    ChannelAccountNotice,
    ChannelDefaults,
    ChannelDescriptor,
    ChannelLeverage,
    ChannelPlugin,
    ChannelUi,
    ChannelUnits,
)
from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_input_accounts import (
    BaseAccountConfig,
    CTPAccountConfig,
    GMAccountConfig,
)

_LEVERAGE = ChannelLeverage(min=0, max=125, step=0.1)
_SINGLE_MAKER = AlgorithmReference(method="SINGLE-MAKER", params={})


def _create_ctp_executor(config: BaseAccountConfig):
    """根据已验证的 CTP 配置创建执行器。"""
    from axile.executor.ctp.ctp_execute import CTPExecutor

    if not isinstance(config, CTPAccountConfig):
        raise TypeError("CTP 渠道需要 CTPAccountConfig")
    return CTPExecutor(TradeChannel.CTP, config)


def _create_gm_executor(config: BaseAccountConfig):
    """根据已验证的掘金配置创建执行器."""
    from axile.executor.gm import GMExecutor

    if not isinstance(config, GMAccountConfig):
        raise TypeError("GM 渠道需要 GMAccountConfig")
    return GMExecutor(config)


def _ctp_plugin() -> ChannelPlugin:
    """构造 CTP 内置渠道插件."""
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel="ctp",
            label="CTP 期货",
            description="通过期货公司柜台连接国内期货市场",
            icon="chart-candlestick",
            market="ctp",
            currency="CNY",
            units=ChannelUnits(
                quantity_kind="contract",
                quantity_label="手",
                quantity_max_decimals=0,
            ),
            defaults=ChannelDefaults(
                long_leverage=3,
                short_leverage=3,
                execution_timeout=180,
                trade_algorithm=AlgorithmReference(method="TARGET-POS-TASK", params={}),
                empty_positions_algorithm=AlgorithmReference(method="TARGET-POS-TASK", params={}),
            ),
            leverage=_LEVERAGE,
            account_form=ChannelAccountForm(
                fields=(
                    ChannelAccountField(name="broker_id", label="期货公司代码", placeholder="如 9999"),
                    ChannelAccountField(name="investor_id", label="投资者号"),
                    ChannelAccountField(name="password", label="密码", input="password"),
                    ChannelAccountField(name="td_front", label="交易前置", required=False, placeholder="tcp://..."),
                    ChannelAccountField(name="md_front", label="行情前置", required=False, placeholder="tcp://..."),
                    ChannelAccountField(name="app_id", label="应用 ID", required=False),
                    ChannelAccountField(name="auth_code", label="授权码", required=False),
                )
            ),
        ),
        account_config_model=CTPAccountConfig,
        create_executor=_create_ctp_executor,
        execution_backend="process",
        required_modules=("openctp_ctp",),
        install_extra="ctp",
    )


def _gm_plugin() -> ChannelPlugin:
    """构造掘金内置渠道插件."""
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel="gm",
            label="掘金 GM",
            description="通过本机终端或 RPC 服务连接掘金量化",
            icon="landmark",
            market="ashare",
            currency="CNY",
            units=ChannelUnits(
                quantity_kind="share",
                quantity_label="股",
                quantity_max_decimals=0,
            ),
            ui=ChannelUi(
                account_connect_lead="账号与 Token 两种连接方式共用；本机终端与 RPC 地址只选一种。",
                leverage_note="A 股仅多头，是投入权益比例",
                long_leverage_label="仓位系数（做多）",
                show_short_leverage=False,
            ),
            defaults=ChannelDefaults(
                long_leverage=1,
                short_leverage=0,
                execution_timeout=180,
                trade_algorithm=_SINGLE_MAKER,
                empty_positions_algorithm=_SINGLE_MAKER,
            ),
            leverage=_LEVERAGE,
            account_form=ChannelAccountForm(
                fields=(
                    ChannelAccountField(name="account_id", label="账号 ID"),
                    ChannelAccountField(name="token", label="Token", input="password"),
                    ChannelAccountField(name="terminal_path", label="本机终端目录", required=False),
                    ChannelAccountField(name="serv_addr", label="终端 RPC 地址", required=False),
                ),
                notices=(ChannelAccountNotice(text="本机终端目录与 RPC 地址必须且只能填写一个。"),),
            ),
        ),
        account_config_model=GMAccountConfig,
        create_executor=_create_gm_executor,
        execution_backend="process",
        required_modules=("gm",),
        install_extra="gm",
    )


def builtin_channel_plugins() -> tuple[ChannelPlugin, ...]:
    """
    按固定展示顺序返回公开包内置渠道.

    Returns
    -------
    tuple[ChannelPlugin, ...]
        依次为 CTP 与掘金渠道插件。
    """
    return (_ctp_plugin(), _gm_plugin())

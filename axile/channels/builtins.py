"""声明公开包内置的 CTP 与 GM 渠道插件."""

from __future__ import annotations

import pandas as pd

from axile.channels.contracts import (
    AlgorithmReference,
    ChannelAccountField,
    ChannelAccountFieldClipboard,
    ChannelAccountFieldCondition,
    ChannelAccountFieldConstraints,
    ChannelAccountForm,
    ChannelAccountNotice,
    ChannelAccountOption,
    ChannelCalendar,
    ChannelDefaults,
    ChannelDescriptor,
    ChannelEndpointConstraints,
    ChannelLeverage,
    ChannelNumberConstraints,
    ChannelPlugin,
    ChannelPortfolioPreset,
    ChannelUi,
    ChannelUnits,
)
from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_input_accounts import (
    BaseAccountConfig,
    CTPAccountConfig,
    GMAccountConfig,
    TQAccountConfig,
)

_LEVERAGE = ChannelLeverage(min=0, max=125, step=0.1)
_SINGLE_MAKER = AlgorithmReference(method="SINGLE-MAKER", params={})


def _contribution_target(config: dict[str, float], frame: pd.DataFrame) -> pd.DataFrame:
    """将策略权重与组合配置相乘并写入贡献度列."""
    frame["contribution"] = frame["weight"] * frame["strategy"].map(config)
    return frame


def _gm_target(config: dict[str, float], frame: pd.DataFrame) -> pd.DataFrame:
    """计算掘金目标贡献度并保持 Axile 通用证券代码."""
    return _contribution_target(config, frame.copy())


def _tq_target(config: dict[str, float], frame: pd.DataFrame) -> pd.DataFrame:
    """计算天勤目标贡献度并保持 Axile 通用合约代码."""
    return _contribution_target(config, frame.copy())


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


def _create_tq_executor(config: BaseAccountConfig):
    """根据已验证的天勤配置创建执行器."""
    from axile.executor.tq import TQExecutor

    if not isinstance(config, TQAccountConfig):
        raise TypeError("天勤渠道需要 TQAccountConfig")
    return TQExecutor(config)


def _ctp_plugin() -> ChannelPlugin:
    """构造 CTP 内置渠道插件."""
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel="ctp",
            label="CTP",
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
            portfolio=ChannelPortfolioPreset(market_label="期货", example_symbols=("rb2610", "ag2612")),
            account_form=ChannelAccountForm(
                fields=(
                    ChannelAccountField(
                        name="broker_id", label="期货公司代码", kind="identifier", width="half", placeholder="如 9999"
                    ),
                    ChannelAccountField(name="investor_id", label="投资者号", kind="identifier", width="half"),
                    ChannelAccountField(name="password", label="密码", kind="secret", width="full"),
                    ChannelAccountField(
                        name="td_front",
                        label="交易前置",
                        kind="endpoint",
                        width="full",
                        placeholder="tcp://...",
                        constraints=ChannelAccountFieldConstraints(
                            endpoint=ChannelEndpointConstraints(
                                scheme="required", allowed_schemes=("tcp",), port="required"
                            )
                        ),
                        clipboard=ChannelAccountFieldClipboard(role="trading", group="ctp-fronts"),
                    ),
                    ChannelAccountField(
                        name="md_front",
                        label="行情前置",
                        kind="endpoint",
                        width="full",
                        placeholder="tcp://...",
                        constraints=ChannelAccountFieldConstraints(
                            endpoint=ChannelEndpointConstraints(
                                scheme="required", allowed_schemes=("tcp",), port="required"
                            )
                        ),
                        clipboard=ChannelAccountFieldClipboard(role="market-data", group="ctp-fronts"),
                    ),
                    ChannelAccountField(name="app_id", label="应用 ID", kind="identifier", width="half"),
                    ChannelAccountField(name="auth_code", label="授权码", kind="secret", width="half"),
                )
            ),
            calendar=ChannelCalendar(calendar_id="china", label="中国交易日历"),
        ),
        account_config_model=CTPAccountConfig,
        create_executor=_create_ctp_executor,
        target_transform=_contribution_target,
        execution_backend="process",
        required_modules=("openctp_ctp",),
        install_extra="ctp",
        max_parallel_symbols=10,
    )


def _gm_plugin() -> ChannelPlugin:
    """构造掘金内置渠道插件."""
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel="gm",
            label="掘金",
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
            portfolio=ChannelPortfolioPreset(
                market_label="A股",
                example_symbols=("600000.SH", "000001.SZ"),
            ),
            account_form=ChannelAccountForm(
                fields=(
                    ChannelAccountField(name="account_id", label="账号 ID", kind="identifier", width="half"),
                    ChannelAccountField(name="token", label="Token", kind="secret", width="half"),
                    ChannelAccountField(
                        name="connection_mode",
                        label="连接方式",
                        kind="select",
                        width="full",
                        default="terminal",
                        presentation="conditional_reveal",
                        help="只需配置其中一种。",
                        options=(
                            ChannelAccountOption(
                                value="terminal",
                                label="本机终端",
                                description="Axile 与掘金终端同机，填写安装目录并由 Axile 检查或启动。",
                            ),
                            ChannelAccountOption(
                                value="service",
                                label="终端 RPC 地址",
                                description="Axile 连接已经运行的终端，支持同机或异机部署。",
                            ),
                        ),
                    ),
                    ChannelAccountField(
                        name="terminal_path",
                        label="本机终端目录",
                        kind="directory",
                        width="full",
                        placeholder=r"C:\Program Files\GoldMiner3",
                        help="填写包含 goldminer3.exe 的安装目录。",
                        visible_when=ChannelAccountFieldCondition(field="connection_mode", equals="terminal"),
                    ),
                    ChannelAccountField(
                        name="serv_addr",
                        label="终端 RPC 地址",
                        kind="endpoint",
                        width="full",
                        placeholder="192.168.1.20:7001",
                        help=(
                            r"先启动掘金终端。地址取自安装目录下 resources\app\gmserv.json 的 "
                            "default.hostAddr 和 default.rpcPort；异机连接需填写 Axile 可访问的 IP，"
                            "不能使用 127.0.0.1。"
                        ),
                        visible_when=ChannelAccountFieldCondition(field="connection_mode", equals="service"),
                        constraints=ChannelAccountFieldConstraints(
                            endpoint=ChannelEndpointConstraints(scheme="forbidden", port="required")
                        ),
                        clipboard=ChannelAccountFieldClipboard(role="rpc"),
                    ),
                ),
            ),
            calendar=ChannelCalendar(calendar_id="china", label="中国交易日历"),
        ),
        account_config_model=GMAccountConfig,
        create_executor=_create_gm_executor,
        target_transform=_gm_target,
        execution_backend="process",
        required_modules=("gm",),
        install_extra="gm",
        max_parallel_symbols=10,
    )


def _tq_plugin() -> ChannelPlugin:
    """构造天勤 TqSdk 内置渠道插件."""
    live = ChannelAccountFieldCondition(field="account_mode", equals="live")
    sim = ChannelAccountFieldCondition(field="account_mode", equals="sim")
    return ChannelPlugin(
        descriptor=ChannelDescriptor(
            channel="tq",
            label="天勤",
            description="通过天勤连接国内期货、期权与组合市场",
            icon="radio-tower",
            market="ctp",
            currency="CNY",
            units=ChannelUnits(
                quantity_kind="contract",
                quantity_label="手",
                quantity_max_decimals=0,
            ),
            ui=ChannelUi(account_connect_lead="选择账户模式后填写对应凭据。"),
            defaults=ChannelDefaults(
                long_leverage=3,
                short_leverage=3,
                execution_timeout=180,
                trade_algorithm=AlgorithmReference(method="TARGET-POS-TASK", params={}),
                empty_positions_algorithm=AlgorithmReference(method="TARGET-POS-TASK", params={}),
            ),
            leverage=_LEVERAGE,
            portfolio=ChannelPortfolioPreset(market_label="期货", example_symbols=("rb2610", "ag2612")),
            account_form=ChannelAccountForm(
                fields=(
                    ChannelAccountField(
                        name="account_mode",
                        label="账户模式",
                        kind="select",
                        width="full",
                        presentation="conditional_reveal",
                        help="选择账户运行方式；天勤账号与密码由三种模式共用。",
                        options=(
                            ChannelAccountOption(
                                value="live",
                                label="实盘账户",
                                description="连接期货公司实盘账户，需填写交易账户凭据。",
                            ),
                            ChannelAccountOption(
                                value="kq",
                                label="快期模拟",
                                description="使用快期模拟账户，无需额外交易账户凭据。",
                            ),
                            ChannelAccountOption(
                                value="sim",
                                label="本地模拟",
                                description="由 Axile 在当前 Worker 中维护模拟资金与持仓。",
                            ),
                        ),
                    ),
                    ChannelAccountField(name="tq_username", label="天勤账号", kind="identifier", width="half"),
                    ChannelAccountField(name="tq_password", label="天勤密码", kind="secret", width="half"),
                    ChannelAccountField(
                        name="broker_name", label="期货公司名称", kind="text", width="half", visible_when=live
                    ),
                    ChannelAccountField(
                        name="account_id", label="交易账户", kind="identifier", width="half", visible_when=live
                    ),
                    ChannelAccountField(
                        name="account_password",
                        label="交易密码",
                        kind="secret",
                        width="full",
                        visible_when=live,
                    ),
                    ChannelAccountField(
                        name="initial_balance",
                        label="初始资金",
                        kind="money",
                        width="full",
                        default=10_000_000,
                        visible_when=sim,
                        constraints=ChannelAccountFieldConstraints(number=ChannelNumberConstraints(gt=0)),
                    ),
                ),
                notices=(
                    ChannelAccountNotice(
                        tone="warning",
                        text="本地模拟状态保存在当前 Worker 中，日盘或夜盘重建后资金与持仓会重置。",
                    ),
                ),
            ),
            calendar=ChannelCalendar(calendar_id="china", label="中国交易日历"),
        ),
        account_config_model=TQAccountConfig,
        create_executor=_create_tq_executor,
        target_transform=_tq_target,
        execution_backend="process",
        required_modules=("tqsdk",),
        install_extra="tqsdk",
        max_parallel_symbols=10,
    )


def builtin_channel_plugins() -> tuple[ChannelPlugin, ...]:
    """
    按固定展示顺序返回公开包内置渠道.

    Returns
    -------
    tuple[ChannelPlugin, ...]
        依次为 CTP、掘金与天勤渠道插件。
    """
    return (_ctp_plugin(), _gm_plugin(), _tq_plugin())

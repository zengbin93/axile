"""持仓管理与目标持仓计算模块."""

import warnings

import loguru

from axile.executor.algorithms.core.base import LoggerProtocol
from axile.executor.ctp.core.market_data import CtpMarketData
from axile.executor.ctp.core.trader import CtpTrader
from axile.executor.models.unified_input import CTPAccountConfig


def account_login(
    account_config: CTPAccountConfig,
    logger: "LoggerProtocol" = loguru.logger,
) -> CtpTrader:
    """
    登录 CTP 账户.

    Parameters
    ----------
    account_config : CTPAccountConfig
        已校验的 CTP 账户配置。
    logger : LoggerProtocol, default=loguru.logger
        日志对象。

    Returns
    -------
    CtpTrader
        已登录的 CTP 交易客户端实例。
    """
    host: str = account_config.td_front or ""
    broker: str = account_config.broker_id
    user: str = account_config.investor_id
    password: str = account_config.password
    appid: str = account_config.app_id or ""
    authcode: str = account_config.auth_code or ""

    trader = CtpTrader(host, broker, user, password, appid, authcode)
    trader.connect()
    trader.login()
    logger.info(f"CTP账户登录成功: {broker} - {user}")
    return trader


def target_volume(
    trader: CtpTrader,
    md_client: CtpMarketData,
    curr_target: dict[str, float],
    last_target: dict[str, float] | None = None,
    logger: "LoggerProtocol" = loguru.logger,
) -> dict[str, int]:
    """
    根据目标持仓权重计算目标持仓数量（已废弃）.

    .. deprecated::
        改用 ``CTPExecutor._calculate_generic_volume`` /
        ``AbstractExecutor.calculate_target_volume``。本函数使用旧版
        ``balance × w / (price × VolumeMultiple)`` 公式，与统一执行框架
        ``total_asset × w / (price × VolumeMultiple)`` 不一致；保留只是
        给历史调用方一个迁移窗口，下个版本将移除。

    Parameters
    ----------
    trader : CtpTrader
        CTP 交易客户端。
    md_client : CtpMarketData
        CTP 行情客户端。
    curr_target : dict[str, float]
        当前目标权重映射。
    last_target : dict[str, float] | None, optional
        上一期目标权重映射。
    logger : LoggerProtocol, default=loguru.logger
        日志对象。

    Returns
    -------
    dict[str, int]
        按品种计算得到的目标手数。
    """
    warnings.warn(
        "axile.executor.ctp.utils.position_manager.target_volume 已废弃，"
        "改用 CTPExecutor._calculate_generic_volume 或 calculate_target_volume；"
        "下一个版本会移除此函数。",
        DeprecationWarning,
        stacklevel=2,
    )
    account = trader.query_account()
    if not account:
        logger.error("查询账户信息失败，无法计算目标持仓")
        return {}
    balance = account.Balance

    last_target_dict: dict[str, float] = last_target or {}
    for symbol in last_target_dict:
        if symbol not in curr_target:
            curr_target[symbol] = 0.0

    positions = trader.get_positions_summary()
    for position in positions:
        if position["instrument_id"] not in curr_target:
            curr_target[position["instrument_id"]] = 0.0

    target_vol_dict: dict[str, int] = {}
    for symbol, weight in curr_target.items():
        quote = md_client.get_quote(symbol)
        if quote is not None:
            last_price = quote.LastPrice
        else:
            position = [p for p in positions if p["instrument_id"] == symbol]
            if position:
                last_price = position[0]["SettlementPrice"]
            else:
                logger.warning(f"未获取到 {symbol} 的 last price，跳过")
                continue

        instrument_info = trader.instruments.get(symbol)
        if not instrument_info:
            logger.warning(f"未获取到 {symbol} 的合约信息，跳过")
            continue

        volume_multiple = instrument_info.VolumeMultiple
        one_slot = last_price * volume_multiple
        target_vol = int(balance * weight / one_slot) if one_slot > 0 else 0

        target_vol_dict[symbol] = target_vol
        logger.info(f"{symbol} - 计算目标持仓数量成功: {target_vol}")

    return target_vol_dict

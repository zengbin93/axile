"""数据转换工具模块 - 支持优化后的objects对象结构."""

import time
from typing import Any, Dict, List, Optional

import loguru
import pandas as pd

from axile.executor.algorithms.core.base import LoggerProtocol
from axile.executor.ctp.core.market_data import CtpMarketData
from axile.executor.ctp.core.objects import (
    DepthMarketDataField,
    InstrumentField,
    PositionField,
    TradingAccountField,
)
from axile.executor.ctp.core.trader import CtpTrader
from axile.executor.ctp.utils.instrument_kind import classify, option_metadata
from axile.executor.models.unified_order import UnifiedOrder


def get_account_assets(
    trader: CtpTrader,
    md_client: CtpMarketData,
    logger: "LoggerProtocol" = loguru.logger,
) -> Dict[str, Any]:
    """
    获取账户资产并返回结构化结果.

    Parameters
    ----------
    trader : CtpTrader
        CTP 交易客户端。
    md_client : CtpMarketData
        CTP 行情客户端。
    logger : LoggerProtocol, default=loguru.logger
        日志对象。

    Returns
    -------
    Dict[str, Any]
        账户资产信息字典。
    """
    logger.info("📊 开始获取账户资产信息...")

    # 查询账户信息（返回Pydantic模型）
    account: Optional[TradingAccountField] = trader.query_account()
    if not account:
        logger.error("❌ 未能获取账户信息")
        raise ValueError("CTP - get_account_assets - 未能获取账户信息")

    available_cash = account.Available
    total_asset = account.Balance
    market_value = 0

    logger.info(f"💰 账户基础信息: 可用资金={available_cash:,.2f}, 总资产={total_asset:,.2f}")

    # 查询持仓（返回Pydantic模型字典）
    positions: Dict[str, PositionField] = trader.query_positions()
    positions_list: List[Dict[str, Any]] = []

    logger.info(f"📈 开始处理 {len(positions)} 个持仓...")

    # 从持仓汇总中获取所有合约代码
    positions_summary: List[Dict[str, Any]] = trader.get_positions_summary()  # type: ignore[assignment]
    symbols: List[str] = [str(position["instrument_id"]) for position in positions_summary]
    md_client.subscribe(symbols)
    time.sleep(1.0)

    for position in positions_summary:  # type: ignore[assignment]
        symbol: str = str(position["instrument_id"])  # 使用字典键访问
        quote: Optional[DepthMarketDataField] = md_client.get_quote(symbol)  # type: ignore[arg-type]

        # 获取合约信息（Pydantic模型）
        instrument_info: Optional[InstrumentField] = trader.instruments.get(symbol)
        volume_multiple = instrument_info.VolumeMultiple if instrument_info else 1

        # 计算持仓方向和数量
        volume: float
        direction: str
        available_volume: float
        if position["net_position"] > 0:
            volume = float(position["net_position"])
            direction = "多头"
            available_volume = float(position["long_position"])  # 假设冻结为0，实际应从详细记录计算
        elif position["net_position"] < 0:
            volume = abs(float(position["net_position"]))
            direction = "空头"
            available_volume = float(position["short_position"])  # 假设冻结为0，实际应从详细记录计算
        else:
            # 如果净持仓为0，跳过
            continue

        # 获取最新价格，如果行情不存在则使用0
        last_price: float
        if quote:
            last_price = float(quote.LastPrice)
        else:
            logger.warning(f"⚠️ 无法获取合约 {symbol} 的行情数据，市值计算可能不准确")
            last_price = float(position["SettlementPrice"])

        # 计算市值（使用净持仓）
        _mv: float = volume * last_price * volume_multiple
        market_value += abs(_mv)

        extra: Dict[str, Any] = {
            "exchange_id": position["exchange_id"],
            "long_position": position.get("long_position", 0),
            "short_position": position.get("short_position", 0),
            "net_position": position.get("net_position", 0),
            "long_yd_position": position.get("long_yd_position", 0),
            "short_yd_position": position.get("short_yd_position", 0),
            "today_position": position.get("today_position", 0),
        }

        # 透传组合拆腿审计字段，便于 UI / 审计追踪原始组合代码。
        combination_origin = position.get("combination_origin")
        if combination_origin:
            extra["combination_origin"] = combination_origin

        # 期权合约补充 metadata：instrument_kind / option_type / strike_price /
        # underlying / underlying_multiple / expire_date。期货合约只标 kind。
        kind = classify(instrument_info)
        extra["instrument_kind"] = kind.value
        if kind.value == "option":
            extra.update(option_metadata(instrument_info))

        _pos: Dict[str, Any] = {
            "symbol": symbol,
            "volume": volume,  # 使用净持仓数量
            "available_volume": available_volume,
            "market_value": _mv,
            "direction": direction,
            "price": last_price,
            "volume_multiple": volume_multiple,
            "extra": extra,
        }
        positions_list.append(_pos)

        logger.debug(f"📍 {symbol}: {direction} {volume}手 (净持仓), 市值={_mv:,.2f}")

    logger.info(f"📊 持仓处理完成: {len(positions_list)}个有效持仓，总市值={market_value:,.2f}")

    account_assets: Dict[str, Any] = {
        "available_cash": available_cash,
        "total_asset": total_asset,
        "market_value": market_value,
        "positions": positions_list,
        "extra": {
            "commission": account.Commission,
            "close_profit": account.CloseProfit,
            "position_profit": account.PositionProfit,
            "frozen_margin": account.FrozenMargin,
            "curr_margin": account.CurrMargin,
            "deposit": account.Deposit,
            "withdraw": account.Withdraw,
            "trading_day": account.TradingDay,
            "currency_id": account.CurrencyID,
            "account_id": account.AccountID,
        },
    }

    total_positions = len(positions)
    processed_positions = len(positions_list)

    logger.info("✅ 账户资产获取完成:")
    logger.info(f"   💰 可用资金: {available_cash:,.2f}")
    logger.info(f"   💼 总资产: {total_asset:,.2f}")
    logger.info(f"   📊 持仓市值: {market_value:,.2f}")
    logger.info(f"   📈 持仓处理: {processed_positions}/{total_positions} 个")

    return account_assets


def get_orders(
    trader: CtpTrader,
    symbols: Optional[List[str]] = None,
    duration: int = 300,
    logger: "LoggerProtocol" = loguru.logger,
) -> List[UnifiedOrder]:
    """
    获取执行订单并返回 ``UnifiedOrder`` 列表.

    Parameters
    ----------
    trader : CtpTrader
        CTP 交易客户端。
    symbols : Optional[List[str]], optional
        合约列表过滤条件。
    duration : int, default=300
        查询时间范围，单位为秒。
    logger : LoggerProtocol, default=loguru.logger
        日志对象。

    Returns
    -------
    List[UnifiedOrder]
        过滤后的统一订单列表。
    """
    logger.info(f"📋 开始获取订单信息，时间范围: {duration}秒")

    # 直接获取UnifiedOrder列表
    unified_orders: List[UnifiedOrder] = trader.get_unified_orders()  # type: ignore[assignment]

    # 应用过滤条件
    start_time = pd.Timestamp.now() - pd.Timedelta(seconds=duration)
    filtered_orders: List[UnifiedOrder] = []

    for order in unified_orders:  # type: ignore[assignment]
        # 时间过滤
        if pd.Timestamp(order.create_time) < start_time:
            continue

        # 符号过滤
        if symbols and order.symbol not in symbols:
            continue

        filtered_orders.append(order)

    logger.info(f"✅ 订单处理完成: {len(filtered_orders)}个相关订单")

    return filtered_orders

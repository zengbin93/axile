"""
QMT 价格数据转换器.

提供 QMT 价格数据与统一模型之间的转换功能。
"""

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

from typing import Any

import pandas as pd

from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_price import UnifiedPriceData


def convert_qmt_tick_to_unified_price(symbol: str, tick: dict[str, Any]) -> UnifiedPriceData:
    """
    将 QMT 的 tick 数据转换为统一价格模型.

    Parameters
    ----------
    symbol : str
        品种代码。
    tick : dict[str, Any]
        QMT 原始 tick 数据字典。

    Returns
    -------
    UnifiedPriceData
        统一价格数据对象。
    """
    dt = pd.to_datetime(tick["timetag"], format="%Y%m%d %H:%M:%S")
    # 按北京时间转换时间戳
    timestamp = int(dt.timestamp() * 1000) - 8 * 3600 * 1000
    dt_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")

    # 获取五档买卖价格和数量
    bid_prices = tick["bidPrice"] if tick["bidPrice"] else []
    ask_prices = tick["askPrice"] if tick["askPrice"] else []
    bid_volumes = tick["bidVol"] if tick["bidVol"] else []
    ask_volumes = tick["askVol"] if tick["askVol"] else []

    unified_price = UnifiedPriceData.model_construct(
        symbol=symbol,
        last_price=float(tick["lastPrice"]),
        # 五档买价
        bid_price=float(bid_prices[0]) if len(bid_prices) > 0 else 0.0,
        bid_price_2=float(bid_prices[1]) if len(bid_prices) > 1 else 0.0,
        bid_price_3=float(bid_prices[2]) if len(bid_prices) > 2 else 0.0,
        bid_price_4=float(bid_prices[3]) if len(bid_prices) > 3 else 0.0,
        bid_price_5=float(bid_prices[4]) if len(bid_prices) > 4 else 0.0,
        # 五档卖价
        ask_price=float(ask_prices[0]) if len(ask_prices) > 0 else 0.0,
        ask_price_2=float(ask_prices[1]) if len(ask_prices) > 1 else 0.0,
        ask_price_3=float(ask_prices[2]) if len(ask_prices) > 2 else 0.0,
        ask_price_4=float(ask_prices[3]) if len(ask_prices) > 3 else 0.0,
        ask_price_5=float(ask_prices[4]) if len(ask_prices) > 4 else 0.0,
        # 五档买量
        bid_volume=float(bid_volumes[0]) if len(bid_volumes) > 0 else 0.0,
        bid_volume_2=float(bid_volumes[1]) if len(bid_volumes) > 1 else 0.0,
        bid_volume_3=float(bid_volumes[2]) if len(bid_volumes) > 2 else 0.0,
        bid_volume_4=float(bid_volumes[3]) if len(bid_volumes) > 3 else 0.0,
        bid_volume_5=float(bid_volumes[4]) if len(bid_volumes) > 4 else 0.0,
        # 五档卖量
        ask_volume=float(ask_volumes[0]) if len(ask_volumes) > 0 else 0.0,
        ask_volume_2=float(ask_volumes[1]) if len(ask_volumes) > 1 else 0.0,
        ask_volume_3=float(ask_volumes[2]) if len(ask_volumes) > 2 else 0.0,
        ask_volume_4=float(ask_volumes[3]) if len(ask_volumes) > 3 else 0.0,
        ask_volume_5=float(ask_volumes[4]) if len(ask_volumes) > 4 else 0.0,
        # 其他字段
        volume=float(tick["volume"]),
        turnover=0.0,  # QMT不提供成交额
        timestamp=timestamp,
        update_time=dt_str,
        extra={
            "channel_type": TradeChannel.QMT,
            "raw_data": tick,
            "stock_status": tick["stockStatus"],
            "open_price": float(tick["open"]),
            "last_close": float(tick["lastClose"]),
            "pvolume": tick["pvolume"],
        },
    )

    return unified_price

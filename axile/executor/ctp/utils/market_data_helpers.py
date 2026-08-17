"""CTP 行情适配与快照辅助工具."""

import time
from datetime import datetime
from typing import Protocol, cast

import loguru

from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.core.base import LoggerProtocol
from axile.executor.ctp.core.market_data import CtpMarketData
from axile.executor.ctp.core.trader import CtpTrader
from axile.executor.models.unified_price import UnifiedPriceData


class _ClockProtocol:
    """最小时钟协议."""

    def sleep(self, _seconds: float) -> None: ...

    def time(self) -> float: ...


def get_default_clock() -> _ClockProtocol:
    """返回默认时钟实现."""

    class _FallbackClock:
        def sleep(self, seconds: float) -> None:
            time.sleep(seconds)

        def time(self) -> float:
            return time.time()

    try:
        from axile.executor.algorithms.utils import get_default_clock as _utils_get_default_clock

        return _utils_get_default_clock()
    except Exception:
        return _FallbackClock()


class _CtpPriceProtocol(Protocol):
    """用于价格适配的最小 CTP tick 协议."""

    TradingDay: str
    UpdateTime: str
    UpdateMillisec: int
    InstrumentID: str
    BidPrice1: float
    BidPrice2: float
    BidPrice3: float
    BidPrice4: float
    BidPrice5: float
    AskPrice1: float
    AskPrice2: float
    AskPrice3: float
    AskPrice4: float
    AskPrice5: float
    BidVolume1: int
    BidVolume2: int
    BidVolume3: int
    BidVolume4: int
    BidVolume5: int
    AskVolume1: int
    AskVolume2: int
    AskVolume3: int
    AskVolume4: int
    AskVolume5: int
    LastPrice: float
    Volume: int
    Turnover: float
    ExchangeID: str
    SettlementPrice: float
    OpenPrice: float
    HighestPrice: float
    LowestPrice: float
    PreClosePrice: float
    OpenInterest: float


def from_ctp_price(
    ctp_data: _CtpPriceProtocol,
    channel_type: TradeChannel = TradeChannel.CTP,
) -> UnifiedPriceData:
    """从 CTP 数据创建统一价格数据."""
    trading_day = ctp_data.TradingDay
    update_time = ctp_data.UpdateTime
    time_ms = ctp_data.UpdateMillisec if hasattr(ctp_data, "UpdateMillisec") else 0

    if "." in update_time:
        datetime_str = f"{trading_day} {update_time}"
        format_str = "%Y%m%d %H:%M:%S.%f"
    else:
        datetime_str = f"{trading_day} {update_time}.{time_ms:03d}"
        format_str = "%Y%m%d %H:%M:%S.%f"

    timestamp = int(datetime.strptime(datetime_str, format_str).timestamp() * 1000)

    model_dump = getattr(ctp_data, "model_dump", None)
    raw_data = cast(dict[str, object], model_dump()) if callable(model_dump) else {}

    return UnifiedPriceData.model_construct(
        symbol=ctp_data.InstrumentID,
        last_price=float(ctp_data.LastPrice),
        bid_price=float(ctp_data.BidPrice1),
        bid_price_2=float(ctp_data.BidPrice2),
        bid_price_3=float(ctp_data.BidPrice3),
        bid_price_4=float(ctp_data.BidPrice4),
        bid_price_5=float(ctp_data.BidPrice5),
        ask_price=float(ctp_data.AskPrice1),
        ask_price_2=float(ctp_data.AskPrice2),
        ask_price_3=float(ctp_data.AskPrice3),
        ask_price_4=float(ctp_data.AskPrice4),
        ask_price_5=float(ctp_data.AskPrice5),
        bid_volume=float(ctp_data.BidVolume1),
        bid_volume_2=float(ctp_data.BidVolume2),
        bid_volume_3=float(ctp_data.BidVolume3),
        bid_volume_4=float(ctp_data.BidVolume4),
        bid_volume_5=float(ctp_data.BidVolume5),
        ask_volume=float(ctp_data.AskVolume1),
        ask_volume_2=float(ctp_data.AskVolume2),
        ask_volume_3=float(ctp_data.AskVolume3),
        ask_volume_4=float(ctp_data.AskVolume4),
        ask_volume_5=float(ctp_data.AskVolume5),
        volume=float(ctp_data.Volume),
        turnover=float(ctp_data.Turnover),
        timestamp=timestamp,
        update_time=update_time,
        extra={
            "channel_type": channel_type,
            "raw_data": raw_data,
            "exchange": ctp_data.ExchangeID,
            "settlement_price": float(ctp_data.SettlementPrice),
            "open_price": float(ctp_data.OpenPrice),
            "high_price": float(ctp_data.HighestPrice),
            "low_price": float(ctp_data.LowestPrice),
            "pre_close": float(ctp_data.PreClosePrice),
            "open_interest": float(ctp_data.OpenInterest),
        },
    )


def get_first_tickers(
    trader: CtpTrader,
    md_client: CtpMarketData,
    symbols: list[str],
    logger: "LoggerProtocol" = loguru.logger,
) -> dict[str, UnifiedPriceData]:
    """获取每个合约的首个 tick，并转换为 UnifiedPriceData."""
    md_client.subscribe(symbols)
    get_default_clock().sleep(2)

    first_ticks: dict[str, UnifiedPriceData] = {}
    for symbol in symbols:
        quote = md_client.get_quote(symbol)
        if not quote:
            logger.warning(f"未获取到 {symbol} 的行情数据")
            continue

        unified_price = from_ctp_price(quote, TradeChannel.CTP)

        instrument_info = trader.instruments.get(symbol)
        volume_multiple = instrument_info.VolumeMultiple if instrument_info else 1
        unified_price.extra.update(
            {
                "volume_multiple": volume_multiple,
                "underlying_symbol": symbol,
            }
        )

        first_ticks[symbol] = unified_price
        logger.info(f"{symbol} - 获取第一个tick成功")

    return first_ticks

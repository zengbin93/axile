"""为非行情专项测试提供满足交易前提的行情。"""

import time

from axile.executor.ctp.converters import quote_to_unified


def fresh_quote(symbol, day):
    now = time.time()
    quote = quote_to_unified(
        dict(
            InstrumentID=symbol,
            TradingDay=day,
            LastPrice=3036,
            BidPrice1=3035,
            AskPrice1=3037,
            BidVolume1=1,
            AskVolume1=1,
            LowerLimitPrice=1,
            UpperLimitPrice=100000,
        )
    )
    quote.timestamp = int(now * 1000)
    quote.extra["received_at"] = now
    return quote

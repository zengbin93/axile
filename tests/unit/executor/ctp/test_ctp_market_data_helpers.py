"""CTP 行情辅助模块单元测试."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_price import UnifiedPriceData


class TestModuleExists:
    """测试模块存在性."""

    def test_ctp_market_data_helpers_module_exists(self) -> None:
        """新的 utils 行情辅助模块文件应存在."""
        module_path = Path("axile/executor/ctp/utils/market_data_helpers.py")

        assert module_path.exists()
        assert importlib.util.spec_from_file_location("ctp_market_data_helpers", module_path) is not None

    def test_legacy_ctp_engine_portfolio_module_is_removed(self) -> None:
        """旧的 engine/portfolio 模块应在迁移后被删除."""
        legacy_module_path = Path("axile/executor/ctp/engine/portfolio.py")

        assert not legacy_module_path.exists()

    def test_legacy_ctp_engine_package_is_removed(self) -> None:
        """旧的 CTP engine 包入口应在迁移后被删除."""
        legacy_package_init = Path("axile/executor/ctp/engine/__init__.py")

        assert not legacy_package_init.exists()


class TestFromCtpPrice:
    """测试 from_ctp_price 函数."""

    @pytest.fixture
    def mock_ctp_price(self):
        """创建模拟 CTP 价格数据."""
        ctp_price = MagicMock()
        ctp_price.InstrumentID = "rb2603"
        ctp_price.TradingDay = "20250319"
        ctp_price.UpdateTime = "15:00:00"
        ctp_price.UpdateMillisec = 500
        ctp_price.LastPrice = 50000.0
        ctp_price.BidPrice1 = 49999.0
        ctp_price.BidPrice2 = 49998.0
        ctp_price.BidPrice3 = 49997.0
        ctp_price.BidPrice4 = 49996.0
        ctp_price.BidPrice5 = 49995.0
        ctp_price.AskPrice1 = 50001.0
        ctp_price.AskPrice2 = 50002.0
        ctp_price.AskPrice3 = 50003.0
        ctp_price.AskPrice4 = 50004.0
        ctp_price.AskPrice5 = 50005.0
        ctp_price.BidVolume1 = 100
        ctp_price.BidVolume2 = 200
        ctp_price.BidVolume3 = 300
        ctp_price.BidVolume4 = 400
        ctp_price.BidVolume5 = 500
        ctp_price.AskVolume1 = 150
        ctp_price.AskVolume2 = 250
        ctp_price.AskVolume3 = 350
        ctp_price.AskVolume4 = 450
        ctp_price.AskVolume5 = 550
        ctp_price.Volume = 12345
        ctp_price.Turnover = 617250000
        ctp_price.ExchangeID = "SHFE"
        ctp_price.SettlementPrice = 50050.0
        ctp_price.OpenPrice = 49500.0
        ctp_price.HighestPrice = 50200.0
        ctp_price.LowestPrice = 49400.0
        ctp_price.PreClosePrice = 49800.0
        ctp_price.OpenInterest = 100000
        ctp_price.model_dump = MagicMock(return_value={"raw": "data"})
        return ctp_price

    def test_from_ctp_price_basic_conversion(self, mock_ctp_price):
        """测试基本的 CTP 价格数据转换."""
        from axile.executor.ctp.utils.market_data_helpers import from_ctp_price

        result = from_ctp_price(mock_ctp_price, TradeChannel.CTP)

        assert isinstance(result, UnifiedPriceData)
        assert result.symbol == "rb2603"
        assert result.last_price == 50000.0
        assert result.bid_price == 49999.0
        assert result.ask_price == 50001.0

    def test_from_ctp_price_timestamp_calculation(self, mock_ctp_price):
        """测试时间戳计算."""
        from axile.executor.ctp.utils.market_data_helpers import from_ctp_price

        result = from_ctp_price(mock_ctp_price, TradeChannel.CTP)

        # 验证时间戳格式（毫秒级）
        assert result.timestamp > 0
        assert len(str(result.timestamp)) == 13  # 毫秒时间戳通常是13位

    def test_from_ctp_price_extra_fields(self, mock_ctp_price):
        """测试额外字段包含."""
        from axile.executor.ctp.utils.market_data_helpers import from_ctp_price

        result = from_ctp_price(mock_ctp_price, TradeChannel.CTP)

        assert "channel_type" in result.extra
        assert "raw_data" in result.extra
        assert "exchange" in result.extra
        assert result.extra["exchange"] == "SHFE"
        assert result.extra["open_price"] == 49500.0
        assert result.extra["pre_close"] == 49800.0

    def test_from_ctp_price_without_millisec(self):
        """测试没有毫秒字段的情况."""
        from axile.executor.ctp.utils.market_data_helpers import from_ctp_price

        ctp_price = MagicMock()
        ctp_price.InstrumentID = "rb2603"
        ctp_price.TradingDay = "20250319"
        ctp_price.UpdateTime = "15:00:00"
        # 不设置 UpdateMillisec 属性
        del ctp_price.UpdateMillisec
        ctp_price.LastPrice = 50000.0
        ctp_price.BidPrice1 = 49999.0
        ctp_price.AskPrice1 = 50001.0
        ctp_price.BidVolume1 = 100
        ctp_price.AskVolume1 = 150
        ctp_price.Volume = 12345
        ctp_price.Turnover = 617250000
        ctp_price.ExchangeID = "SHFE"
        ctp_price.SettlementPrice = 50050.0
        ctp_price.OpenPrice = 49500.0
        ctp_price.HighestPrice = 50200.0
        ctp_price.LowestPrice = 49400.0
        ctp_price.PreClosePrice = 49800.0
        ctp_price.OpenInterest = 100000
        ctp_price.model_dump = MagicMock(return_value={})

        result = from_ctp_price(ctp_price, TradeChannel.CTP)

        assert result.symbol == "rb2603"
        assert result.last_price == 50000.0


class TestGetFirstTickers:
    """测试 get_first_tickers 函数."""

    @pytest.fixture
    def fake_clock(self):
        """创建仅记录 sleep 调用的假时钟."""

        class _FakeClock:
            def __init__(self) -> None:
                self.sleep_calls: list[float] = []

            def time(self) -> float:
                return 0.0

            def sleep(self, seconds: float) -> None:
                self.sleep_calls.append(seconds)

            def event_wait(self, event: object, timeout: float) -> bool:
                return bool(getattr(event, "wait")(timeout))

        return _FakeClock()

    @pytest.fixture
    def mock_trader(self):
        """创建模拟交易器."""
        trader = MagicMock()
        instrument = MagicMock()
        instrument.VolumeMultiple = 10
        trader.instruments = {"rb2603": instrument}
        return trader

    @pytest.fixture
    def mock_md_client(self):
        """创建模拟行情客户端."""
        md_client = MagicMock()
        mock_quote = MagicMock()
        mock_quote.InstrumentID = "rb2603"
        mock_quote.TradingDay = "20250319"
        mock_quote.UpdateTime = "15:00:00"
        mock_quote.UpdateMillisec = 500
        mock_quote.LastPrice = 50000.0
        mock_quote.BidPrice1 = 49999.0
        mock_quote.AskPrice1 = 50001.0
        mock_quote.BidVolume1 = 100
        mock_quote.AskVolume1 = 150
        mock_quote.Volume = 12345
        mock_quote.Turnover = 617250000
        mock_quote.ExchangeID = "SHFE"
        mock_quote.SettlementPrice = 50050.0
        mock_quote.OpenPrice = 49500.0
        mock_quote.HighestPrice = 50200.0
        mock_quote.LowestPrice = 49400.0
        mock_quote.PreClosePrice = 49800.0
        mock_quote.OpenInterest = 100000
        mock_quote.model_dump = MagicMock(return_value={})

        md_client.get_quote = MagicMock(return_value=mock_quote)
        md_client.subscribe = MagicMock()
        return md_client

    def test_get_first_tickers_success(self, mock_trader, mock_md_client, mock_logger, fake_clock, monkeypatch):
        """测试成功获取首个 tick."""
        from axile.executor.ctp.utils import market_data_helpers

        monkeypatch.setattr(market_data_helpers, "get_default_clock", lambda: fake_clock)
        result = market_data_helpers.get_first_tickers(
            mock_trader,
            mock_md_client,
            ["rb2603"],
            mock_logger,
        )

        assert "rb2603" in result
        assert result["rb2603"].symbol == "rb2603"
        assert result["rb2603"].last_price == 50000.0
        assert fake_clock.sleep_calls == [2]

    def test_get_first_tickers_no_quote(self, mock_trader, mock_md_client, mock_logger, fake_clock, monkeypatch):
        """测试未获取到行情数据的情况."""
        from axile.executor.ctp.utils import market_data_helpers

        # 设置返回 None
        mock_md_client.get_quote = MagicMock(return_value=None)
        monkeypatch.setattr(market_data_helpers, "get_default_clock", lambda: fake_clock)

        result = market_data_helpers.get_first_tickers(
            mock_trader,
            mock_md_client,
            ["rb2603"],
            mock_logger,
        )

        assert result == {}
        assert fake_clock.sleep_calls == [2]

    def test_get_first_tickers_volume_multiple_included(
        self,
        mock_trader,
        mock_md_client,
        mock_logger,
        fake_clock,
        monkeypatch,
    ):
        """测试成交量乘数包含在结果中."""
        from axile.executor.ctp.utils import market_data_helpers

        monkeypatch.setattr(market_data_helpers, "get_default_clock", lambda: fake_clock)

        result = market_data_helpers.get_first_tickers(
            mock_trader,
            mock_md_client,
            ["rb2603"],
            mock_logger,
        )

        assert "rb2603" in result
        assert result["rb2603"].extra.get("volume_multiple") == 10
        assert fake_clock.sleep_calls == [2]


@pytest.fixture
def mock_logger():
    """创建模拟 logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.debug = MagicMock()
    logger.error = MagicMock()
    return logger

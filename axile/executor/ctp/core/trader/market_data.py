"""``CtpTrader`` 行情客户端代理 mixin.

把 ``self.md_client`` 的常用方法包装成 trader 实例方法，方便上层调用方
不必直接访问 md_client 属性，并允许 trader 在客户端缺失时给出统一日志。
"""

# Mixin 共享属性（self.logger / self.md_client / self.md_front 等）由 _main.py
# 的 __init__ 初始化，pyright 无法静态推断；用文件级 reportAttributeAccessIssue
# 抑制这一类告警。其它检查项保持开启，以便业务函数仍能受到类型检查保护。
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from typing import Any

from axile.executor.ctp.core.objects import DepthMarketDataField
from axile.executor.ctp.core.trader._constants import get_default_clock


class MarketDataMixin:
    """行情客户端的代理方法（内部统一委托给 ``self.md_client``）。"""

    def init_market_data(self, md_front: str | None = None):
        """
        初始化行情客户端.

        Parameters
        ----------
        md_front : str | None, optional
            行情前置地址；未提供时使用初始化时的地址。
        """
        if md_front:
            self.md_front = md_front

        if not self.md_front:
            self.logger.warning("⚠️  没有提供行情前置地址，无法初始化行情客户端")
            return False

        try:
            from axile.executor.ctp.core.market_data import CtpMarketData

            self.md_client = CtpMarketData(self.md_front, account_id=f"{self.broker}_{self.user}")
            self.logger.info(f"✅ 行情客户端初始化成功: {self.md_front}")
            return True
        except (
            AttributeError,
            ImportError,
            KeyError,
            LookupError,
            ModuleNotFoundError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            self.logger.error(f"❌ 行情客户端初始化失败: {e}")
            return False

    def connect_market_data(self, _auto_retry: bool = True):
        """连接行情客户端."""
        if not self.md_client:
            if not self.md_front:
                self.logger.warning("⚠️  没有行情前置地址，无法连接行情")
                return False
            self.init_market_data(md_front=self.md_front)
            if not self.md_client:
                return False

        try:
            self.md_client.connect()
            self.md_connected = True
            self.logger.info("✅ 行情客户端连接成功")
            return True
        except (
            AttributeError,
            KeyError,
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            self.logger.error(f"❌ 行情客户端连接失败: {e}")
            self.md_connected = False
            return False

    def subscribe_market_data(self, symbols: list[str]):
        """订阅行情数据."""
        if not self.md_client:
            self.logger.warning("⚠️  行情客户端未初始化，尝试自动初始化...")
            if not self.connect_market_data():
                return False

        if not self.md_connected:
            self.logger.warning("⚠️  行情客户端未连接，尝试连接...")
            if not self.connect_market_data():
                return False

        try:
            if self.md_client:
                self.md_client.subscribe(symbols)
                self.logger.info(f"📡 订阅行情成功: {symbols}")
                return True
            else:
                self.logger.error("❌ 行情客户端未初始化")
                return False
        except (
            AttributeError,
            KeyError,
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            self.logger.error(f"❌ 订阅行情失败: {e}")
            return False

    def get_quote(self, symbol: str) -> DepthMarketDataField | None:
        """获取指定合约的行情数据."""
        if not self.md_client:
            self.logger.debug(f"⚠️  行情客户端未初始化，无法获取 {symbol} 的行情")
            return None

        quote = self.md_client.get_quote(symbol)
        if not quote:
            self.logger.debug(f"⚠️  未获取到 {symbol} 的行情数据")

        return quote

    def get_all_quotes(self) -> dict[str, DepthMarketDataField]:
        """获取所有已订阅合约的行情数据."""
        if not self.md_client:
            return {}

        return self.md_client.quotes.copy()

    def get_market_data_status(self) -> dict[str, Any]:
        """获取行情客户端状态."""
        if not self.md_client:
            return {
                "initialized": False,
                "connected": False,
                "subscribed_count": 0,
                "quote_count": 0,
                "total_ticks": 0,
            }

        return {
            "initialized": True,
            "connected": self.md_client.connected and self.md_client.logged_in,
            "subscribed_count": len(self.md_client.subscribed_symbols),
            "quote_count": len(self.md_client.quotes),
            "total_ticks": self.md_client.quote_count,
            "subscribed_symbols": list(self.md_client.subscribed_symbols),
            "available_quotes": list(self.md_client.quotes.keys()),
        }

    def log_market_data_status(self):
        """记录行情客户端状态概览."""
        status = self.get_market_data_status()

        self.logger.info("=" * 50)
        self.logger.info("📡 行情客户端状态概览")
        self.logger.info("=" * 50)

        if not status["initialized"]:
            self.logger.info("❌ 行情客户端未初始化")
        else:
            self.logger.info("✅ 行情客户端已初始化")
            self.logger.info(f"🔌 连接状态: {'已连接' if status['connected'] else '未连接'}")
            self.logger.info(f"📊 订阅合约: {status['subscribed_count']} 个")
            self.logger.info(f"📈 活跃行情: {status['quote_count']} 个")
            self.logger.info(f"🔢 总tick数: {status['total_ticks']}")

            if status["available_quotes"]:
                self.logger.info("📋 可用行情:")
                for symbol in status["available_quotes"][:10]:
                    quote = self.get_quote(symbol)
                    if quote:
                        self.logger.info(f"  {symbol}: {quote.LastPrice} @{quote.UpdateTime}")

                if len(status["available_quotes"]) > 10:
                    self.logger.info(f"  ... 还有 {len(status['available_quotes']) - 10} 个")

        self.logger.info("=" * 50)

    def ensure_quote_available(self, symbol: str, auto_subscribe: bool = True) -> bool:
        """
        确保指定合约的行情可用.

        Parameters
        ----------
        symbol : str
            合约代码。
        auto_subscribe : bool, default=True
            如果没有行情，是否自动订阅。

        Returns
        -------
        bool
            行情是否可用。
        """
        quote = self.get_quote(symbol)
        if quote:
            return True

        if not auto_subscribe:
            return False

        self.logger.info(f"🔄 {symbol} 行情不可用，尝试自动订阅...")

        if not self.md_connected:
            if not self.connect_market_data():
                return False

        if self.subscribe_market_data([symbol]):
            for _i in range(10):
                get_default_clock().sleep(0.5)
                if self.get_quote(symbol):
                    self.logger.info(f"✅ {symbol} 行情订阅成功")
                    return True

            self.logger.warning(f"⚠️  {symbol} 订阅后仍无行情数据")

        return False

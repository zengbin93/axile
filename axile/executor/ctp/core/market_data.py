"""
管理 CTP 行情连接、报价缓存与统一价格回调.

该模块负责维护行情前置的生命周期，包括连接登录、断线重连、订阅恢复、
本地报价快照缓存，以及将原始 CTP tick 转换为统一价格模型后分发给回调。
"""

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import threading
import time
from typing import Protocol

import loguru

from axile.executor.algorithms.core.base import LoggerProtocol
from axile.executor.ctp.core import openctp_compat as ctp_compat
from axile.executor.ctp.core.objects import CtpConverter, DepthMarketDataField
from axile.executor.ctp.core.reconnect import ReconnectController, ReconnectPolicy
from axile.executor.models.unified_callback import PriceDataCallback
from axile.executor.models.unified_price import UnifiedPriceData


class CtpMarketDataTimeoutError(TimeoutError):
    """当行情操作超出超时时间时抛出."""


class CtpMarketDataCancelledError(RuntimeError):
    """当行情操作在关闭过程中被取消时抛出."""


def _wait_or_raise(
    event: threading.Event,
    timeout: float,
    message: str,
    *,
    stop_event: threading.Event | None = None,
    poll_interval: float = 0.1,
) -> None:
    """等待事件触发，或抛出带类型的超时异常."""
    deadline = time.time() + timeout

    while True:
        if stop_event and stop_event.is_set():
            raise CtpMarketDataCancelledError(f"{message}，已收到停止请求")

        remaining = deadline - time.time()
        if remaining <= 0:
            raise CtpMarketDataTimeoutError(message)

        wait_timeout = min(remaining, poll_interval)
        if event.wait(wait_timeout):
            if stop_event and stop_event.is_set():
                raise CtpMarketDataCancelledError(f"{message}，已收到停止请求")
            return


def _safe_release_api(api: object | None) -> None:
    """释放当前 API 实例，并屏蔽清理阶段的噪音异常."""
    if api is None:
        return

    try:
        api.RegisterSpi(None)
    except (AttributeError, OSError, RuntimeError):
        pass

    try:
        api.Release()
    except (AttributeError, OSError, RuntimeError):
        return


class _RspInfoProtocol(Protocol):
    """最小化的 CTP 响应信息协议."""

    ErrorID: int
    ErrorMsg: str


class _InstrumentProtocol(Protocol):
    """最小化的 CTP 合约标识协议."""

    InstrumentID: str


class CtpMarketData:
    """
    管理 CTP 行情会话和本地报价快照.

    Notes
    -----
    行情线程既负责更新 ``quotes`` 缓存，也负责向外部分发统一价格回调。
    因此缓存与回调注册表分别由独立锁保护，避免高频 tick 因日志或回调管理阻塞。
    """

    def __init__(
        self,
        md_front: str,
        account_id: str | None = None,
        verbose: bool = False,
        logger: "LoggerProtocol | None" = None,
    ) -> None:
        """
        初始化行情客户端.

        Parameters
        ----------
        md_front : str
            行情前置地址。
        account_id : str | None, optional
            账户标识，用于隔离 CTP flow 临时目录。
        verbose : bool, default=False
            是否启用详细日志。
        logger : LoggerProtocol | None, optional
            日志对象。
        """
        self.md_front = md_front
        self.account_id = account_id
        self.api: object | None = None
        self._spi_proxy: object | None = None
        self.verbose = verbose
        self.logger: LoggerProtocol = logger or loguru.logger
        self.quotes: dict[str, DepthMarketDataField] = {}

        self.connected = False
        self.logged_in = False

        self.connect_event = threading.Event()
        self.login_event = threading.Event()
        self.stop_event = threading.Event()
        self.subscribe_events: dict[str, threading.Event] = {}

        self.quote_count = 0
        self.subscribed_symbols: set[str] = set()

        self.reconnect = ReconnectController(
            name="行情",
            policy=ReconnectPolicy(
                enable_auto_reconnect=True,
                max_reconnect_attempts=5,
                reconnect_interval=3.0,
                connection_timeout=30.0,
            ),
            attempt_reconnect=self._attempt_reconnect,
            on_reconnect_success=self._resubscribe_symbols,
            logger=self.logger,
        )
        self.reconnect_config = self.reconnect.policy

        self._price_callbacks: list[PriceDataCallback] = []
        self._callbacks_lock = threading.Lock()
        self._quotes_lock = threading.RLock()

    def connect(self) -> None:
        """连接行情."""
        self.stop_event.clear()
        self.api = self._create_md_api()
        self.api.Init()

        _wait_or_raise(
            self.connect_event,
            self.reconnect.policy.connection_timeout,
            "连接行情服务器超时",
            stop_event=self.stop_event,
        )
        _wait_or_raise(
            self.login_event,
            self.reconnect.policy.connection_timeout,
            "行情登录超时",
            stop_event=self.stop_event,
        )

    def _create_md_api(self) -> object:
        """创建行情API实例."""
        import os
        import tempfile

        from axile.executor.ctp.utils.temp_cleaner import build_ctp_flow_path, register_temp_path

        temp_dir = tempfile.gettempdir()
        flow_path = build_ctp_flow_path(temp_dir, self.account_id, "md")
        os.makedirs(flow_path, exist_ok=True)
        register_temp_path(flow_path)

        ctp_compat.ensure_openctp_loaded()
        api = ctp_compat.CThostFtdcMdApi.CreateFtdcMdApi(flow_path)
        self._spi_proxy = ctp_compat.create_md_spi_proxy(self)
        api.RegisterFront(self.md_front)
        api.RegisterSpi(self._spi_proxy)
        return api

    def OnFrontConnected(self) -> None:
        """行情前置连接回调."""
        self.logger.info("行情前置连接成功")
        self.connected = True
        self.connect_event.set()

        req = ctp_compat.mdapi.CThostFtdcReqUserLoginField()
        if self.api:
            try:
                self.api.ReqUserLogin(req, 0, False, req.UserProductInfo)
            except TypeError:
                # OpenCTP 不同版本暴露的登录签名不一致，这里优先走新签名并向旧版本回退。
                self.api.ReqUserLogin(req, 0)

    def OnFrontDisconnected(self, nReason: int) -> None:
        """行情前置断开回调."""
        self.logger.error(f"🔌 行情前置连接断开: {nReason}")
        self.connected = False
        self.logged_in = False
        self.reconnect.notify_disconnect()

    def _attempt_reconnect(self) -> bool:
        """尝试重连."""
        try:
            # 重连必须丢弃旧 API 和旧事件状态，否则可能把上一次会话留下的 set 状态误当成新连接成功。
            _safe_release_api(self.api)
            self.api = self._create_md_api()
            self.connect_event.clear()
            self.login_event.clear()
            self.api.Init()
            _wait_or_raise(
                self.connect_event,
                self.reconnect_config.connection_timeout,
                "连接超时",
                stop_event=self.stop_event,
            )
            _wait_or_raise(
                self.login_event,
                self.reconnect_config.connection_timeout,
                "登录超时",
                stop_event=self.stop_event,
            )

            return True

        except (
            AttributeError,
            CtpMarketDataCancelledError,
            CtpMarketDataTimeoutError,
            OSError,
            RuntimeError,
            ValueError,
        ) as e:
            self.logger.error(f"行情重连失败: {e}")
            return False

    def _resubscribe_symbols(self) -> None:
        """重新订阅已订阅的合约."""
        if self.subscribed_symbols:
            try:
                symbols_list = list(self.subscribed_symbols)
                self.logger.info(f"🔄 重新订阅 {len(symbols_list)} 个合约...")
                self.subscribe(symbols_list)
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
                self.logger.error(f"重新订阅合约失败: {e}")

    def stop_auto_reconnect(self) -> None:
        """停止自动重连."""
        self.logger.info("🛑 停止行情自动重连...")
        self.reconnect.stop(timeout=3.0)
        if self.reconnect.is_running:
            self.logger.warning("⚠️  行情重连线程未能正常停止")
        else:
            self.logger.info("✅ 行情重连线程已停止")

    def OnRspUserLogin(
        self,
        _pRspUserLogin: object,
        pRspInfo: _RspInfoProtocol | None,
        _nRequestID: int,
        _bIsLast: bool,
    ) -> None:
        """行情登录响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"行情登录失败: {pRspInfo.ErrorMsg}")
            self.login_event.set()
            return

        self.logger.info("行情登录成功")
        self.logged_in = True
        self.login_event.set()

    def subscribe(self, symbols: list[str]) -> None:
        """
        订阅行情.

        Parameters
        ----------
        symbols : list[str]
            需要订阅的合约列表，例如 ``["rb2310", "hc2310"]``。
        """
        if not symbols:
            return

        if not self.api:
            self.logger.error("行情API未初始化，无法订阅行情")
            return

        symbol_bytes = [symbol.encode("utf-8") for symbol in symbols]
        self.api.SubscribeMarketData(symbol_bytes, len(symbols))

        for symbol in symbols:
            self.subscribe_events[symbol] = threading.Event()

        # 每个 symbol 单独等待确认，这样批量订阅里部分成功、部分失败时不会被最后一个响应掩盖。
        for symbol in symbols:
            try:
                _wait_or_raise(
                    self.subscribe_events[symbol],
                    10,
                    f"订阅 {symbol} 超时",
                    stop_event=self.stop_event,
                )
                self.subscribed_symbols.add(symbol)
            except CtpMarketDataCancelledError:
                self.logger.info(f"订阅 {symbol} 已取消")
                raise
            except CtpMarketDataTimeoutError:
                self.logger.warning(f"订阅 {symbol} 超时")

        self.logger.info(f"订阅完成，成功订阅 {len(self.subscribed_symbols)} 个合约")

    def OnRspSubMarketData(
        self,
        pSpecificInstrument: _InstrumentProtocol | None,
        pRspInfo: _RspInfoProtocol | None,
        _nRequestID: int,
        _bIsLast: bool,
    ) -> None:
        """订阅行情响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"订阅行情失败: {pRspInfo.ErrorMsg}")
            return

        if pSpecificInstrument:
            symbol = pSpecificInstrument.InstrumentID
            self.logger.info(f"订阅 {symbol} 成功")
            if symbol in self.subscribe_events:
                self.subscribe_events[symbol].set()

    def OnRtnDepthMarketData(self, pDepthMarketData: _InstrumentProtocol | None) -> None:
        """行情数据回调."""
        if pDepthMarketData:
            self._process_market_data(pDepthMarketData)

    def _process_market_data(self, pDepthMarketData: _InstrumentProtocol) -> None:
        """处理行情数据."""
        symbol = pDepthMarketData.InstrumentID

        quote_model = CtpConverter.tick_to_model(pDepthMarketData)

        # 先更新缓存，再做统计和回调，保证同步回调里查询 ``get_quote`` 能看到同一笔最新快照。
        with self._quotes_lock:
            self.quotes[symbol] = quote_model

        self._update_quote_stats(quote_model)
        self._dispatch_price_data(quote_model)

    def _update_quote_stats(self, quote_model: DepthMarketDataField) -> None:
        """
        更新行情统计信息，并控制日志采样频率.

        Parameters
        ----------
        quote_model : DepthMarketDataField
            最新收到的行情快照。

        Notes
        -----
        该逻辑运行在高频 tick 回调线程上，只允许做常数级计数和采样日志，
        避免每笔报价都触发 I/O 导致行情线程积压。
        """
        self.quote_count += 1

        if self.verbose and self.quote_count % 100 == 0:
            self._log_quote_details(quote_model)

        if self.quote_count % 100 == 0:
            with self._quotes_lock:
                quotes_count = len(self.quotes)
            self.logger.debug(f"行情统计: 已接收 {self.quote_count} 个tick，订阅合约 {quotes_count} 个")

    def _log_quote_details(self, quote: DepthMarketDataField) -> None:
        """记录行情详细信息（仅debug模式）."""
        change, change_pct = self._calculate_price_change(quote)

        self.logger.debug(f"📈 行情更新: {quote.InstrumentID}")
        self.logger.debug(f"   价格信息: 最新价={quote.LastPrice}, 涨跌={change:+.2f} ({change_pct:+.2f}%)")
        self.logger.debug(
            f"   成交信息: 成交量={quote.Volume}, 成交额={quote.Turnover:,.0f}, 持仓量={quote.OpenInterest}"
        )
        self.logger.debug(
            f"   买卖档位: 买1={quote.BidPrice1}×{quote.BidVolume1}, 卖1={quote.AskPrice1}×{quote.AskVolume1}"
        )
        self.logger.debug(f"   更新时间: {quote.UpdateTime}.{quote.UpdateMillisec:03d}")

    def _calculate_price_change(self, quote: DepthMarketDataField) -> tuple[float, float]:
        """计算价格涨跌和涨跌幅."""
        if quote.PreSettlementPrice <= 0:
            return 0.0, 0.0

        change = quote.LastPrice - quote.PreSettlementPrice
        change_pct = (change / quote.PreSettlementPrice) * 100
        return change, change_pct

    def get_quote(self, symbol: str) -> DepthMarketDataField | None:
        """
        获取行情.

        Parameters
        ----------
        symbol : str
            合约代码。

        Returns
        -------
        DepthMarketDataField | None
            行情数据对象；若无数据则返回 ``None``。
        """
        with self._quotes_lock:
            return self.quotes.get(symbol)

    def get_quote_summary(self, symbol: str) -> dict[str, object] | None:
        """获取行情摘要信息."""
        with self._quotes_lock:
            quote = self.quotes.get(symbol)

        if not quote:
            return None

        change, change_pct = self._calculate_price_change(quote)

        return {
            "instrument_id": quote.InstrumentID,
            "last_price": quote.LastPrice,
            "change": change,
            "change_pct": change_pct,
            "volume": quote.Volume,
            "turnover": quote.Turnover,
            "open_interest": quote.OpenInterest,
            "bid_price1": quote.BidPrice1,
            "bid_volume1": quote.BidVolume1,
            "ask_price1": quote.AskPrice1,
            "ask_volume1": quote.AskVolume1,
            "update_time": f"{quote.UpdateTime}.{quote.UpdateMillisec:03d}",
            "trading_day": quote.TradingDay,
        }

    def get_all_quotes_summary(self) -> list[dict[str, object]]:
        """获取所有订阅合约的行情摘要."""
        summaries = []

        with self._quotes_lock:
            symbols = list(self.quotes.keys())

        for symbol in symbols:
            summary = self.get_quote_summary(symbol)
            if summary:
                summaries.append(summary)

        return sorted(summaries, key=lambda x: x["instrument_id"])

    def is_market_active(self, symbol: str) -> bool:
        """基于最近快照内容启发式判断市场是否活跃."""
        with self._quotes_lock:
            quote = self.quotes.get(symbol)

        if not quote:
            return False

        return quote.LastPrice > 0 and quote.Volume > 0

    def log_market_status(self) -> None:
        """记录行情状态概览."""
        self.logger.info("=" * 50)
        self.logger.info("CTP行情客户端状态概览")
        self.logger.info("=" * 50)

        self.logger.info(f"连接状态: 连接={self.connected}, 登录={self.logged_in}")
        self.logger.info(f"行情服务器: {self.md_front}")

        with self._quotes_lock:
            quotes_count = len(self.quotes)
            all_symbols = list(self.quotes.keys())

        self.logger.info(f"订阅合约: {quotes_count}个")
        self.logger.info(f"接收tick总数: {self.quote_count}个")

        active_symbols = [symbol for symbol in all_symbols if self.is_market_active(symbol)]
        if active_symbols:
            self.logger.info(f"活跃合约: {len(active_symbols)}个")
            for symbol in active_symbols[:5]:
                summary = self.get_quote_summary(symbol)
                if summary:
                    self.logger.info(
                        f"  {summary['instrument_id']}: "
                        f"{summary['last_price']} "
                        f"({summary['change']:+.2f}, {summary['change_pct']:+.2f}%) "
                        f"成交量={summary['volume']}"
                    )
        else:
            self.logger.info("活跃合约: 0个")

        self.logger.info("=" * 50)

    def register_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注册价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            价格数据回调函数。
        """
        with self._callbacks_lock:
            if callback not in self._price_callbacks:
                self._price_callbacks.append(callback)
                self.logger.info(f"✅ 注册价格回调成功，当前回调数: {len(self._price_callbacks)}")
            else:
                self.logger.warning("价格回调已注册")

    def unregister_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注销价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            要注销的价格回调函数。
        """
        with self._callbacks_lock:
            if callback in self._price_callbacks:
                self._price_callbacks.remove(callback)
                self.logger.info(f"✅ 注销价格回调成功，当前回调数: {len(self._price_callbacks)}")
            else:
                self.logger.warning("价格回调未注册")

    def _dispatch_price_data(self, quote: DepthMarketDataField) -> None:
        """
        分发价格数据到所有注册的回调函数.

        Parameters
        ----------
        quote : DepthMarketDataField
            CTP 行情数据模型。
        """
        with self._callbacks_lock:
            callbacks = self._price_callbacks.copy()

        if not callbacks:
            return

        try:
            # 统一模型在扇出前只构造一次，保证所有回调看到一致的时间戳与档位快照。
            unified_price = UnifiedPriceData.model_construct(
                symbol=quote.InstrumentID,
                last_price=float(quote.LastPrice) if quote.LastPrice else 0.0,
                bid_price=float(quote.BidPrice1) if quote.BidPrice1 else 0.0,
                ask_price=float(quote.AskPrice1) if quote.AskPrice1 else 0.0,
                bid_volume=float(quote.BidVolume1) if quote.BidVolume1 else 0.0,
                ask_volume=float(quote.AskVolume1) if quote.AskVolume1 else 0.0,
                volume=float(quote.Volume) if quote.Volume else 0.0,
                timestamp=int(time.time() * 1000),
                update_time=f"{quote.UpdateTime}.{quote.UpdateMillisec:03d}" if quote.UpdateTime else "",
            )
        except (AttributeError, TypeError, ValueError) as e:
            self.logger.error(f"转换价格数据失败: {e}")
            return

        for callback in callbacks:
            try:
                callback(unified_price)
            except (AttributeError, RuntimeError, TypeError, ValueError) as e:
                self.logger.error(f"价格回调执行失败: {e}")

    def get_price_callback_count(self) -> int:
        """
        获取当前注册的价格回调函数数量.

        Returns
        -------
        int
            当前注册的价格回调函数数量。
        """
        with self._callbacks_lock:
            return len(self._price_callbacks)

    def close(self) -> None:
        """关闭连接."""
        self.request_stop()

        # 先唤醒所有等待中的连接/订阅，再停掉重连线程，避免关闭流程被后台等待拖住。
        self.stop_auto_reconnect()

        if hasattr(self, "api") and self.api:
            _safe_release_api(self.api)
            self.api = None
            self.connected = False
            self.logged_in = False
            self.logger.info("🔌 行情连接已关闭")

    def request_stop(self) -> None:
        """请求中止当前等待中的连接或订阅流程."""
        self.stop_event.set()
        self.connect_event.set()
        self.login_event.set()
        for event in list(self.subscribe_events.values()):
            event.set()

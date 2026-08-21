"""
GM 回调分发器.

管理订单、成交和价格数据的回调注册和分发。
提供线程安全的统一回调接口。
"""

import threading
from collections import deque
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from loguru import logger

from axile.executor.models.unified_callback import OrderUpdateCallback, PriceDataCallback, TradeRecordCallback
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData

GMRuntimeLogLevel: TypeAlias = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class GMRuntimeLogEvent:
    """
    GM runtime 日志事件.

    Attributes
    ----------
    level : GMRuntimeLogLevel
        日志级别。
    message : str
        日志正文。
    source : str
        事件来源标识。
    timestamp : str
        事件生成时间，使用 ISO 8601 字符串。
    """

    level: GMRuntimeLogLevel
    message: str
    source: str
    timestamp: str


class GMRuntimeLogCallback(Protocol):
    """
    GM runtime 日志回调协议.

    Notes
    -----
    该协议用于接收 bridge runtime 发出的结构化日志事件。
    """

    def __call__(self, event: GMRuntimeLogEvent) -> None:
        """
        处理 GM runtime 日志事件.

        Parameters
        ----------
        event : GMRuntimeLogEvent
            结构化日志事件对象。
        """
        ...


class GMCallbackDispatcher:
    """GM 回调分发器.

    线程安全的回调分发器，用于管理和分发订单、成交和价格更新事件。
    """

    def __init__(self) -> None:
        """初始化回调分发器."""
        self._order_callbacks: list[OrderUpdateCallback] = []
        self._trade_callbacks: list[TradeRecordCallback] = []
        self._price_callbacks: list[PriceDataCallback] = []
        self._runtime_log_callbacks: list[GMRuntimeLogCallback] = []
        self._order_observers: list[OrderUpdateCallback] = []
        self._trade_observers: list[TradeRecordCallback] = []
        self._runtime_logs: deque[GMRuntimeLogEvent] = deque(maxlen=200)
        self._callbacks_lock = threading.Lock()

        # 统计信息
        self._stats = {
            "order_updates_received": 0,
            "trade_records_received": 0,
            "price_updates_received": 0,
            "runtime_logs_received": 0,
        }

        logger.debug("[GM] CallbackDispatcher 初始化完成")

    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注册订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            符合 ``OrderUpdateCallback`` 协议的回调函数。
        """
        with self._callbacks_lock:
            if callback not in self._order_callbacks:
                self._order_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注册订单回调: {callback_name}")
            else:
                logger.warning(f"[GM] 订单回调已注册: {callback}")

    def register_order_observer(self, callback: OrderUpdateCallback) -> None:
        """注册内部订单观察者，不计入对外回调数量."""
        with self._callbacks_lock:
            if callback not in self._order_observers:
                self._order_observers.append(callback)

    def register_trade_observer(self, callback: TradeRecordCallback) -> None:
        """注册内部成交观察者，不计入对外回调数量."""
        with self._callbacks_lock:
            if callback not in self._trade_observers:
                self._trade_observers.append(callback)

    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注册成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            符合 ``TradeRecordCallback`` 协议的回调函数。
        """
        with self._callbacks_lock:
            if callback not in self._trade_callbacks:
                self._trade_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注册成交回调: {callback_name}")
            else:
                logger.warning(f"[GM] 成交回调已注册: {callback}")

    def register_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注册价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            符合 ``PriceDataCallback`` 协议的回调函数。
        """
        with self._callbacks_lock:
            if callback not in self._price_callbacks:
                self._price_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注册价格回调: {callback_name}")
            else:
                logger.warning(f"[GM] 价格回调已注册: {callback}")

    def register_runtime_log_callback(self, callback: GMRuntimeLogCallback) -> None:
        """
        注册 GM runtime 日志回调函数.

        Parameters
        ----------
        callback : GMRuntimeLogCallback
            用于接收 GM runtime 日志事件的回调函数。
        """
        with self._callbacks_lock:
            if callback not in self._runtime_log_callbacks:
                self._runtime_log_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注册 runtime 日志回调: {callback_name}")
            else:
                logger.warning(f"[GM] runtime 日志回调已注册: {callback}")

    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注销订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            要注销的回调函数。
        """
        with self._callbacks_lock:
            if callback in self._order_callbacks:
                self._order_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注销订单回调: {callback_name}")
            else:
                logger.warning(f"[GM] 订单回调未注册: {callback}")

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注销成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            要注销的回调函数。
        """
        with self._callbacks_lock:
            if callback in self._trade_callbacks:
                self._trade_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注销成交回调: {callback_name}")
            else:
                logger.warning(f"[GM] 成交回调未注册: {callback}")

    def unregister_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注销价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            要注销的回调函数。
        """
        with self._callbacks_lock:
            if callback in self._price_callbacks:
                self._price_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注销价格回调: {callback_name}")
            else:
                logger.warning(f"[GM] 价格回调未注册: {callback}")

    def unregister_runtime_log_callback(self, callback: GMRuntimeLogCallback) -> None:
        """
        注销 GM runtime 日志回调函数.

        Parameters
        ----------
        callback : GMRuntimeLogCallback
            要注销的 runtime 日志回调函数。
        """
        with self._callbacks_lock:
            if callback in self._runtime_log_callbacks:
                self._runtime_log_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"[GM] 已注销 runtime 日志回调: {callback_name}")
            else:
                logger.warning(f"[GM] runtime 日志回调未注册: {callback}")

    def dispatch_order_update(self, order: UnifiedOrder) -> None:
        """
        分发订单更新到所有注册的回调函数.

        Parameters
        ----------
        order : UnifiedOrder
            统一格式的订单信息。
        """
        self._stats["order_updates_received"] += 1

        with self._callbacks_lock:
            observers = self._order_observers.copy()
            callbacks = self._order_callbacks.copy()

        for observer in observers:
            try:
                observer(order)
            except Exception as e:
                callback_name = getattr(observer, "__name__", "unknown")
                logger.error(f"[GM] 内部订单观察者 {callback_name} 出错: {e}", exc_info=True)

        if not callbacks:
            return

        logger.debug(f"[GM] 正在分发订单更新到 {len(callbacks)} 个监听器: {order.order_id} - {order.status}")

        for callback in callbacks:
            try:
                callback(order)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"[GM] 订单回调 {callback_name} 出错: {e}", exc_info=True)

    def dispatch_trade_record(self, trade: TradeRecord) -> None:
        """
        分发成交记录到所有注册的回调函数.

        Parameters
        ----------
        trade : TradeRecord
            统一格式的成交记录。
        """
        self._stats["trade_records_received"] += 1

        with self._callbacks_lock:
            observers = self._trade_observers.copy()
            callbacks = self._trade_callbacks.copy()

        for observer in observers:
            try:
                observer(trade)
            except Exception as e:
                callback_name = getattr(observer, "__name__", "unknown")
                logger.error(f"[GM] 内部成交观察者 {callback_name} 出错: {e}", exc_info=True)

        if not callbacks:
            return

        logger.debug(f"[GM] 正在分发成交记录到 {len(callbacks)} 个监听器: {trade.trade_id}")

        for callback in callbacks:
            try:
                callback(trade)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"[GM] 成交回调 {callback_name} 出错: {e}", exc_info=True)

    def dispatch_price_data(self, price_data: UnifiedPriceData) -> None:
        """
        分发价格数据到所有注册的回调函数.

        Parameters
        ----------
        price_data : UnifiedPriceData
            统一格式的价格数据。
        """
        self._stats["price_updates_received"] += 1

        with self._callbacks_lock:
            callbacks = self._price_callbacks.copy()

        if not callbacks:
            return

        logger.debug(f"[GM] 正在分发价格更新到 {len(callbacks)} 个监听器: {price_data.symbol}")

        for callback in callbacks:
            try:
                callback(price_data)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"[GM] 价格回调 {callback_name} 出错: {e}", exc_info=True)

    def dispatch_runtime_log(self, event: GMRuntimeLogEvent) -> None:
        """
        分发 GM runtime 日志事件.

        Parameters
        ----------
        event : GMRuntimeLogEvent
            结构化 runtime 日志事件。
        """
        self._stats["runtime_logs_received"] += 1

        with self._callbacks_lock:
            # 先保留最近一段 runtime 日志，供后续可能接入 execution audit
            # 或其他上游消费者时直接复用，不在当前版本引入额外副作用。
            self._runtime_logs.append(event)
            callbacks = self._runtime_log_callbacks.copy()

        if not callbacks:
            return

        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"[GM] runtime 日志回调 {callback_name} 出错: {e}", exc_info=True)

    def get_recent_runtime_logs(self, limit: int = 100) -> list[GMRuntimeLogEvent]:
        """
        获取最近收到的 GM runtime 日志事件.

        Parameters
        ----------
        limit : int, default=100
            返回的最大事件数量。

        Returns
        -------
        list[GMRuntimeLogEvent]
            按接收顺序排列的最近日志事件列表。
        """
        effective_limit = max(limit, 0)
        with self._callbacks_lock:
            if effective_limit == 0:
                return []
            return list(self._runtime_logs)[-effective_limit:]

    def get_callback_count(self) -> dict[str, int]:
        """
        获取当前注册的回调函数数量.

        Returns
        -------
        dict[str, int]
            包含各类对外回调数量的字典。
        """
        with self._callbacks_lock:
            return {
                "order_callbacks": len(self._order_callbacks),
                "trade_callbacks": len(self._trade_callbacks),
                "price_callbacks": len(self._price_callbacks),
            }

    def get_stats(self) -> dict[str, int]:
        """
        获取回调统计信息.

        Returns
        -------
        dict[str, int]
            包含各类回调累计接收次数的字典。
        """
        return self._stats.copy()

    def clear_all_callbacks(self) -> None:
        """清除所有注册的回调函数."""
        with self._callbacks_lock:
            self._order_callbacks.clear()
            self._trade_callbacks.clear()
            self._price_callbacks.clear()
        logger.info("[GM] 已清除所有回调函数")

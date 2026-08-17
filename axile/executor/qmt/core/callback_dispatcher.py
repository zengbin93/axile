"""
QMT 回调分发器.

管理订单、成交和价格数据的回调注册和分发。
与统一回调分发契约保持一致的接口设计。
"""

import threading

from loguru import logger

from axile.executor.models.unified_callback import OrderUpdateCallback, PriceDataCallback, TradeRecordCallback
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


class QMTCallbackDispatcher:
    """
    QMT 回调分发器.

    Notes
    -----
    该分发器以线程安全方式管理订单、成交和价格回调，以及内部观察者。
    """

    def __init__(self) -> None:
        """初始化回调分发器."""
        self._order_callbacks: list[OrderUpdateCallback] = []
        self._trade_callbacks: list[TradeRecordCallback] = []
        self._price_callbacks: list[PriceDataCallback] = []
        self._order_observers: list[OrderUpdateCallback] = []
        self._trade_observers: list[TradeRecordCallback] = []
        self._callbacks_lock = threading.Lock()

        logger.debug("QMTCallbackDispatcher 初始化完成")

    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注册订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            符合订单回调协议的可调用对象。
        """
        with self._callbacks_lock:
            if callback not in self._order_callbacks:
                self._order_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"已注册订单回调: {callback_name}")
            else:
                logger.warning(f"订单回调已注册: {callback}")

    def register_order_observer(self, callback: OrderUpdateCallback) -> None:
        """
        注册内部订单观察者，不计入对外回调数量.

        Parameters
        ----------
        callback : OrderUpdateCallback
            内部使用的订单观察者回调。
        """
        with self._callbacks_lock:
            if callback not in self._order_observers:
                self._order_observers.append(callback)

    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注册成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            符合成交回调协议的可调用对象。
        """
        with self._callbacks_lock:
            if callback not in self._trade_callbacks:
                self._trade_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"已注册成交回调: {callback_name}")
            else:
                logger.warning(f"成交回调已注册: {callback}")

    def register_trade_observer(self, callback: TradeRecordCallback) -> None:
        """
        注册内部成交观察者，不计入对外回调数量.

        Parameters
        ----------
        callback : TradeRecordCallback
            内部使用的成交观察者回调。
        """
        with self._callbacks_lock:
            if callback not in self._trade_observers:
                self._trade_observers.append(callback)

    def register_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注册价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            符合价格回调协议的可调用对象。
        """
        with self._callbacks_lock:
            if callback not in self._price_callbacks:
                self._price_callbacks.append(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"已注册价格回调: {callback_name}")
            else:
                logger.warning(f"价格回调已注册: {callback}")

    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注销订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            待注销的订单回调函数。
        """
        with self._callbacks_lock:
            if callback in self._order_callbacks:
                self._order_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"已注销订单回调: {callback_name}")
            else:
                logger.warning(f"订单回调未注册: {callback}")

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注销成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            待注销的成交回调函数。
        """
        with self._callbacks_lock:
            if callback in self._trade_callbacks:
                self._trade_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"已注销成交回调: {callback_name}")
            else:
                logger.warning(f"成交回调未注册: {callback}")

    def unregister_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注销价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            待注销的价格回调函数。
        """
        with self._callbacks_lock:
            if callback in self._price_callbacks:
                self._price_callbacks.remove(callback)
                callback_name = getattr(callback, "__name__", "unknown")
                logger.info(f"已注销价格回调: {callback_name}")
            else:
                logger.warning(f"价格回调未注册: {callback}")

    def dispatch_order_update(self, order: UnifiedOrder) -> None:
        """
        分发订单更新到所有注册的回调函数.

        Parameters
        ----------
        order : UnifiedOrder
            统一格式的订单信息。
        """
        with self._callbacks_lock:
            observers = self._order_observers.copy()
            callbacks = self._order_callbacks.copy()

        for observer in observers:
            try:
                observer(order)
            except Exception as e:
                callback_name = getattr(observer, "__name__", "unknown")
                logger.error(f"订单观察者 {callback_name} 出错: {e}", exc_info=True)

        if not callbacks:
            return

        logger.debug(f"正在分发订单更新到 {len(callbacks)} 个监听器: {order.order_id}")

        for callback in callbacks:
            try:
                callback(order)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"订单回调 {callback_name} 出错: {e}", exc_info=True)

    def dispatch_trade_record(self, trade: TradeRecord) -> None:
        """
        分发成交记录到所有注册的回调函数.

        Parameters
        ----------
        trade : TradeRecord
            统一格式的成交记录。
        """
        with self._callbacks_lock:
            observers = self._trade_observers.copy()
            callbacks = self._trade_callbacks.copy()

        for observer in observers:
            try:
                observer(trade)
            except Exception as e:
                callback_name = getattr(observer, "__name__", "unknown")
                logger.error(f"成交观察者 {callback_name} 出错: {e}", exc_info=True)

        if not callbacks:
            return

        logger.debug(f"正在分发成交记录到 {len(callbacks)} 个监听器: {trade.trade_id}")

        for callback in callbacks:
            try:
                callback(trade)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"成交回调 {callback_name} 出错: {e}", exc_info=True)

    def dispatch_price_data(self, price_data: UnifiedPriceData) -> None:
        """
        分发价格数据到所有注册的回调函数.

        Parameters
        ----------
        price_data : UnifiedPriceData
            统一格式的价格数据。
        """
        with self._callbacks_lock:
            callbacks = self._price_callbacks.copy()

        if not callbacks:
            return

        logger.debug(f"正在分发价格更新到 {len(callbacks)} 个监听器: {price_data.symbol}")

        for callback in callbacks:
            try:
                callback(price_data)
            except Exception as e:
                callback_name = getattr(callback, "__name__", "unknown")
                logger.error(f"价格回调 {callback_name} 出错: {e}", exc_info=True)

    def get_callback_count(self) -> dict[str, int]:
        """
        获取当前注册的回调函数数量.

        Returns
        -------
        dict[str, int]
            包含各类回调计数的字典。
        """
        with self._callbacks_lock:
            return {
                "order_callbacks": len(self._order_callbacks),
                "trade_callbacks": len(self._trade_callbacks),
                "price_callbacks": len(self._price_callbacks),
            }

    def clear_all_callbacks(self) -> None:
        """清除所有注册的回调函数."""
        with self._callbacks_lock:
            self._order_callbacks.clear()
            self._trade_callbacks.clear()
            self._price_callbacks.clear()
        logger.info("已清除所有回调函数")

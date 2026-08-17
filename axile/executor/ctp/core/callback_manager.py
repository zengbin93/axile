"""
管理 CTP 订单与成交回调的注册和分发.

该模块把内部观察者与对外回调分开维护：观察者用于执行器内部状态同步，
对外回调则暴露给账户层或策略层消费统一事件。
"""

from __future__ import annotations

import threading
from typing import Dict, List

import loguru

from axile.executor.models.unified_callback import OrderUpdateCallback, TradeRecordCallback
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder


class CallbackManager:
    """
    管理订单更新和成交记录回调.

    Notes
    -----
    该类会先分发内部观察者，再分发对外回调，确保执行器内部状态更新
    不会被外部回调的耗时或异常打乱顺序。
    """

    def __init__(self, logger: loguru.Logger | None = None) -> None:
        """
        初始化回调管理器.

        Parameters
        ----------
        logger : loguru.Logger | None, optional
            日志记录器；为 ``None`` 时使用 ``loguru.logger``。
        """
        self._logger = logger or loguru.logger
        self._order_callbacks: List[OrderUpdateCallback] = []
        self._trade_callbacks: List[TradeRecordCallback] = []
        self._order_observers: List[OrderUpdateCallback] = []
        self._trade_observers: List[TradeRecordCallback] = []
        self._lock = threading.Lock()

    def register_order_callback(self, callback: OrderUpdateCallback) -> bool:
        """
        注册订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            订单更新回调函数。

        Returns
        -------
        bool
            注册成功时返回 ``True``；若回调已存在则返回 ``False``。
        """
        with self._lock:
            if callback not in self._order_callbacks:
                self._order_callbacks.append(callback)
                self._logger.debug(f"✅ 注册订单回调成功，当前回调数: {len(self._order_callbacks)}")
                return True
            else:
                self._logger.warning("⚠️ 订单回调已注册，跳过重复注册")
                return False

    def unregister_order_callback(self, callback: OrderUpdateCallback) -> bool:
        """
        注销订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            要注销的订单回调函数。

        Returns
        -------
        bool
            注销成功时返回 ``True``；若回调不存在则返回 ``False``。
        """
        with self._lock:
            if callback in self._order_callbacks:
                self._order_callbacks.remove(callback)
                self._logger.debug(f"✅ 注销订单回调成功，当前回调数: {len(self._order_callbacks)}")
                return True
            return False

    def register_order_observer(self, callback: OrderUpdateCallback) -> bool:
        """注册内部订单观察者，不计入对外回调数量."""
        with self._lock:
            if callback not in self._order_observers:
                self._order_observers.append(callback)
                return True
            return False

    def dispatch_order_callback(self, order: UnifiedOrder) -> None:
        """
        分发订单更新回调.

        Parameters
        ----------
        order : UnifiedOrder
            统一格式的订单对象。

        Notes
        -----
        回调列表会先在锁内复制快照，再在锁外执行，避免回调内部再次注册、
        注销或查询状态时与分发线程互相阻塞。
        """
        with self._lock:
            observers = self._order_observers.copy()
            callbacks = self._order_callbacks.copy()

        # 内部观察者优先执行，保证订单跟踪器等内部状态机先看到原始事件。
        for observer in observers:
            try:
                observer(order)
            except Exception as e:
                self._logger.error(f"❌ 订单观察者执行失败: {e}")

        for callback in callbacks:
            try:
                callback(order)
            except Exception as e:
                self._logger.error(f"❌ 订单回调执行失败: {e}")

    def register_trade_callback(self, callback: TradeRecordCallback) -> bool:
        """
        注册成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            成交记录回调函数。

        Returns
        -------
        bool
            注册成功时返回 ``True``；若回调已存在则返回 ``False``。
        """
        with self._lock:
            if callback not in self._trade_callbacks:
                self._trade_callbacks.append(callback)
                self._logger.debug(f"✅ 注册成交回调成功，当前回调数: {len(self._trade_callbacks)}")
                return True
            else:
                self._logger.warning("⚠️ 成交回调已注册，跳过重复注册")
                return False

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> bool:
        """
        注销成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            要注销的成交回调函数。

        Returns
        -------
        bool
            注销成功时返回 ``True``；若回调不存在则返回 ``False``。
        """
        with self._lock:
            if callback in self._trade_callbacks:
                self._trade_callbacks.remove(callback)
                self._logger.debug(f"✅ 注销成交回调成功，当前回调数: {len(self._trade_callbacks)}")
                return True
            return False

    def register_trade_observer(self, callback: TradeRecordCallback) -> bool:
        """注册内部成交观察者，不计入对外回调数量."""
        with self._lock:
            if callback not in self._trade_observers:
                self._trade_observers.append(callback)
                return True
            return False

    def dispatch_trade_callback(self, trade: TradeRecord) -> None:
        """
        分发成交记录回调.

        Parameters
        ----------
        trade : TradeRecord
            统一格式的成交记录对象。

        Notes
        -----
        成交事件与订单事件遵循相同的分发策略：锁内复制快照，锁外执行回调，
        并优先通知内部观察者。
        """
        with self._lock:
            observers = self._trade_observers.copy()
            callbacks = self._trade_callbacks.copy()

        for observer in observers:
            try:
                observer(trade)
            except Exception as e:
                self._logger.error(f"❌ 成交观察者执行失败: {e}")

        for callback in callbacks:
            try:
                callback(trade)
            except Exception as e:
                self._logger.error(f"❌ 成交回调执行失败: {e}")

    def get_callback_count(self) -> Dict[str, int]:
        """
        获取当前注册的回调函数数量.

        Returns
        -------
        Dict[str, int]
            包含 ``order_callbacks`` 和 ``trade_callbacks`` 数量的字典。
        """
        with self._lock:
            return {
                "order_callbacks": len(self._order_callbacks),
                "trade_callbacks": len(self._trade_callbacks),
            }

    def clear(self) -> None:
        """清空所有已注册的回调函数."""
        with self._lock:
            self._order_callbacks.clear()
            self._trade_callbacks.clear()
            self._logger.debug("✅ 已清空所有回调函数")

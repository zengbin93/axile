#!/usr/bin/env python3
"""
统一回调协议与抽象客户端模型.

定义订单、成交与行情回调的统一协议，以及回调客户端需要实现的抽象接口。
"""

from abc import ABC, abstractmethod
from typing import Protocol

from axile.executor.models.unified_order import TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData

# ===== 回调协议定义 =====


class OrderUpdateCallback(Protocol):
    """
    订单更新回调协议.

    Notes
    -----
    该协议用于约束订单更新回调函数的签名，便于静态类型检查与实现统一。
    """

    def __call__(self, order: UnifiedOrder) -> None:
        """
        处理订单更新事件.

        Parameters
        ----------
        order : UnifiedOrder
            包含最新状态变化的统一订单对象。
        """
        ...


class TradeRecordCallback(Protocol):
    """
    成交记录回调协议.

    Notes
    -----
    该协议用于约束成交回调函数的签名，便于静态类型检查与实现统一。
    """

    def __call__(self, trade: TradeRecord) -> None:
        """
        处理成交记录事件.

        Parameters
        ----------
        trade : TradeRecord
            包含成交明细的统一成交记录对象。
        """
        ...


class PriceDataCallback(Protocol):
    """
    价格数据回调协议.

    Notes
    -----
    该协议用于约束行情回调函数的签名，便于静态类型检查与实现统一。
    """

    def __call__(self, price_data: UnifiedPriceData) -> None:
        """
        处理价格数据更新事件.

        Parameters
        ----------
        price_data : UnifiedPriceData
            包含最新盘口与成交量的统一行情快照。
        """
        ...


# ===== 回调客户端抽象基类 =====


class UnifiedCallbackClient(ABC):
    """
    统一回调客户端抽象基类.

    Notes
    -----
    实现类通常需要负责以下事项：

    1. 维护订单与成交回调的注册列表。
    2. 提供监控状态查询与停止能力。
    3. 保证回调分发过程中的线程安全与异常隔离。
    """

    # ===== 回调注册接口 =====

    @abstractmethod
    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注册订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            符合订单更新回调协议的可调用对象。

        Notes
        -----
        实现类通常应避免重复注册，并以线程安全方式维护回调列表。
        """
        ...

    @abstractmethod
    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注册成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            符合成交记录回调协议的可调用对象。

        Notes
        -----
        实现类通常应避免重复注册，并以线程安全方式维护回调列表。
        """
        ...

    # ===== 状态查询接口 =====

    @abstractmethod
    def is_monitoring(self) -> bool:
        """
        返回当前是否处于监控状态.

        Returns
        -------
        bool
            正在监控时返回 ``True``，否则返回 ``False``。
        """
        ...

    # ===== 控制接口 =====

    @abstractmethod
    def stop(self) -> None:
        """
        停止回调客户端并清理资源.

        Notes
        -----
        实现类应停止事件监听或分发过程，并在返回前尽量完成必要的资源释放。
        """
        ...

    # ===== 可选扩展接口 =====

    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注销订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            待注销的回调函数。

        Notes
        -----
        该接口为可选实现，默认行为为空操作。
        """

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注销成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            待注销的回调函数。

        Notes
        -----
        该接口为可选实现，默认行为为空操作。
        """

    def get_callback_count(self) -> dict[str, int]:
        """
        返回当前注册的回调函数数量.

        Returns
        -------
        dict[str, int]
            包含 ``order_callbacks`` 与 ``trade_callbacks`` 计数的字典。

        Notes
        -----
        该接口为可选实现，默认返回空字典。
        """
        return {}

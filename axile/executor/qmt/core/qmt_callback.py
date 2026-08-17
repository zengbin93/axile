"""
QMT 交易回调处理器.

基于 XtQuantTraderCallback 实现的回调处理器，将 QMT 原始回调事件转换为统一格式并分发。

主要功能：
- 接收 QMT 的订单、成交、错误回调
- 将 QMT 原始数据转换为统一模型格式
- 通过 QMTCallbackDispatcher 分发到注册的回调函数
"""

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

from datetime import datetime
from typing import cast

from loguru import logger
from xtquant.xttrader import XtQuantTraderCallback  # type: ignore
from xtquant.xttype import XtCancelError, XtOrder, XtOrderError, XtTrade  # type: ignore

from axile.executor.algorithms.core.base import LoggerProtocol
from axile.executor.qmt.converters.order_converter import (
    convert_qmt_order_to_unified,
    convert_qmt_trade_to_trade_record,
)
from axile.executor.qmt.core.callback_dispatcher import QMTCallbackDispatcher


class QMTTraderCallback(XtQuantTraderCallback):
    """
    QMT 交易回调处理器.

    Notes
    -----
    该处理器继承自 ``XtQuantTraderCallback``，负责接收 QMT 原始回调事件，
    将其转换为统一模型后分发给上层监听器。
    """

    def __init__(
        self,
        callback_dispatcher: QMTCallbackDispatcher,
        **kwargs: object,
    ) -> None:
        """
        初始化回调处理器.

        Parameters
        ----------
        callback_dispatcher : QMTCallbackDispatcher
            回调分发器实例。
        **kwargs : object
            额外参数；支持通过 ``logger`` 传入日志对象。
        """
        self.callback_dispatcher = callback_dispatcher
        self._logger = cast(LoggerProtocol, kwargs.get("logger", logger))

        # 统计信息
        self.stats = {
            "orders_received": 0,
            "trades_received": 0,
            "errors_received": 0,
            "cancel_errors_received": 0,
            "async_responses_received": 0,
        }

        self._logger.info("QMTTraderCallback 初始化完成")

    def on_disconnected(self) -> None:
        """连接断开回调."""
        self._logger.warning(f"[{datetime.now().isoformat()}] QMT 连接断开")

    def on_stock_order(self, order: XtOrder) -> None:
        """
        处理委托回报推送.

        Parameters
        ----------
        order : XtOrder
            QMT 原始委托对象。
        """
        self.stats["orders_received"] += 1

        try:
            # 转换为统一订单格式
            unified_order = convert_qmt_order_to_unified(order)

            self._logger.debug(
                f"收到订单回报: {order.stock_code} 状态={unified_order.status} 备注={order.order_remark}"
            )

            # 分发到回调
            self.callback_dispatcher.dispatch_order_update(unified_order)

        except Exception as e:
            self._logger.error(f"处理订单回调失败: {e}", exc_info=True)

    def on_stock_trade(self, trade: XtTrade) -> None:
        """
        处理成交变动推送.

        Parameters
        ----------
        trade : XtTrade
            QMT 原始成交对象。
        """
        self.stats["trades_received"] += 1

        try:
            # 转换为统一成交记录格式
            trade_record = convert_qmt_trade_to_trade_record(trade)

            self._logger.debug(
                f"收到成交回报: {trade.stock_code} "
                f"价格={trade.traded_price} "
                f"数量={trade.traded_volume} "
                f"方向={'买入' if trade.offset_flag == 48 else '卖出'}"
            )

            # 分发到回调
            self.callback_dispatcher.dispatch_trade_record(trade_record)

        except Exception as e:
            self._logger.error(f"处理成交回调失败: {e}", exc_info=True)

    def on_order_error(self, order_error: XtOrderError) -> None:
        """
        处理委托失败推送.

        Parameters
        ----------
        order_error : XtOrderError
            包含委托错误信息的对象。
        """
        self.stats["errors_received"] += 1

        self._logger.error(
            f"[{datetime.now().isoformat()}] 委托报错回调: "
            f"order_id={order_error.order_id} "
            f"error_id={order_error.error_id} "
            f"error_msg={order_error.error_msg} "
            f"备注={order_error.order_remark}"
        )

    def on_cancel_error(self, cancel_error: XtCancelError) -> None:
        """
        处理撤单失败推送.

        Parameters
        ----------
        cancel_error : XtCancelError
            包含撤单错误信息的对象。
        """
        self.stats["cancel_errors_received"] += 1

        self._logger.error(f"[{datetime.now().isoformat()}] 撤单报错回调: {str(cancel_error)}")

    def on_order_stock_async_response(self, response: object) -> None:
        """
        处理异步下单回报推送.

        Parameters
        ----------
        response : object
            异步下单响应对象。
        """
        self.stats["async_responses_received"] += 1

        self._logger.debug(
            f"[{datetime.now().isoformat()}] 异步委托回调: "
            f"seq={getattr(response, 'seq', 'N/A')} "
            f"备注={getattr(response, 'order_remark', 'N/A')}"
        )

    def on_cancel_order_stock_async_response(self, response: object) -> None:
        """
        处理异步撤单回报推送.

        Parameters
        ----------
        response : object
            异步撤单响应对象。
        """
        self._logger.debug(f"[{datetime.now().isoformat()}] 异步撤单回调: seq={getattr(response, 'seq', 'N/A')}")

    def on_account_status(self, status: object) -> None:
        """
        处理账户状态变化推送.

        Parameters
        ----------
        status : object
            账户状态对象。
        """
        self._logger.debug(f"[{datetime.now().isoformat()}] 账户状态回调: {str(status)}")

    def get_stats(self) -> dict[str, int]:
        """
        获取统计信息.

        Returns
        -------
        dict[str, int]
            当前累计的回调统计信息副本。
        """
        return self.stats.copy()

    def reset_stats(self) -> None:
        """重置统计信息."""
        for key in self.stats:
            self.stats[key] = 0
        self._logger.debug("统计信息已重置")

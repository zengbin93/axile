"""``CtpTrader`` 订单生命周期 / 撤单 / 成交 / 结算单 / 状态汇总 mixin."""

# Mixin 共享属性（self.logger / self.api / self.orders 等）由 _main.py 的
# __init__ 初始化，pyright 无法静态推断；用文件级 reportAttributeAccessIssue
# 抑制。handle_ctp_error 装饰器签名 (object, **P) -> R 触发 reportArgumentType，
# 故一并抑制。
# pyright: reportAttributeAccessIssue=false
# pyright: reportArgumentType=false

from __future__ import annotations

import threading
from datetime import date
from typing import Any, Callable

import pandas as pd

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.decorators import controlled_operation
from axile.executor.ctp.core.error_handler import CTP_COMMON_EXCEPTIONS, handle_ctp_error, safe_callback
from axile.executor.ctp.core.objects import (
    CancelOrderStatusType,
    CtpConverter,
    DirectionType,
    OffsetFlagType,
    OrderField,
    OrderPriceType,
    OrderStatusType,
    TradeField,
)
from axile.executor.ctp.core.openctp_compat import (
    THOST_FTDC_TC_GFD,
    THOST_FTDC_VC_AV,
    CThostFtdcInputOrderActionField,
    CThostFtdcInputOrderField,
    CThostFtdcQryOrderField,
    CThostFtdcQrySettlementInfoField,
    CThostFtdcQryTradeField,
    THOST_FTDC_AF_Delete,
    THOST_FTDC_CC_Immediately,
    THOST_FTDC_D_Buy,
    THOST_FTDC_D_Sell,
    THOST_FTDC_FCC_NotForceClose,
    THOST_FTDC_HF_Speculation,
    THOST_FTDC_OF_Close,
    THOST_FTDC_OF_CloseToday,
    THOST_FTDC_OF_CloseYesterday,
    THOST_FTDC_OF_Open,
    THOST_FTDC_OPT_LimitPrice,
)
from axile.executor.ctp.core.trader._constants import (
    CTP_TD_GLOBAL_GROUP,
    _safe_decode_content,
    _wait_or_raise,
    get_default_clock,
)
from axile.executor.models.unified_callback import OrderUpdateCallback, TradeRecordCallback
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder


class OrdersMixin:
    """订单 / 成交 / 结算单查询 + 下单 + 撤单 + 回调注册。"""

    # ---- 订单过滤 ---------------------------------------------------------

    def _should_keep_order(self, order: OrderField) -> bool:
        """
        判断是否应该保留该订单.

        Parameters
        ----------
        order : OrderField
            订单模型对象。

        Returns
        -------
        bool
            需要保留时返回 ``True``，否则返回 ``False``。
        """
        # 1. 检查订单状态 - 过滤掉已完成的订单
        terminal_states = {
            OrderStatusType.ALL_TRADED,  # 全部成交
            OrderStatusType.CANCELED,  # 撤单
            OrderStatusType.PART_TRADED_NOT_QUEUEING,  # 部分成交不在队列中
            OrderStatusType.NO_TRADE_NOT_QUEUEING,  # 未成交不在队列中
        }

        # 如果是终态订单，检查是否是当天的订单
        if order.OrderStatus in terminal_states:
            # 检查是否是今天的订单，只保留今天的订单（包括已完成的）
            if hasattr(order, "InsertDate") and order.InsertDate:
                try:
                    if len(order.InsertDate) == 8:
                        insert_date = date(
                            int(order.InsertDate[:4]),
                            int(order.InsertDate[4:6]),
                            int(order.InsertDate[6:8]),
                        )
                        today = date.today()
                        if insert_date < today:
                            return False  # 过滤掉历史已完成订单
                except (ValueError, TypeError):
                    pass

        # 2. 检查订单是否过期（基于时间条件）
        if hasattr(order, "TimeCondition") and order.TimeCondition:
            # GFD = 当日有效，如果不是当日订单则过滤
            if order.TimeCondition == "3":  # GFD - 当日有效
                if hasattr(order, "InsertDate") and order.InsertDate:
                    try:
                        if len(order.InsertDate) == 8:
                            insert_date = date(
                                int(order.InsertDate[:4]),
                                int(order.InsertDate[4:6]),
                                int(order.InsertDate[6:8]),
                            )
                            today = date.today()
                            if insert_date < today:
                                return False  # 过期订单
                    except (ValueError, TypeError):
                        pass

        # 3. 保留所有活跃订单和当天的订单（无论状态）
        return True

    # ---- 订单 / 成交查询 --------------------------------------------------

    @controlled_operation(
        "query_orders",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="fetched",
    )
    def query_orders(
        self,
        instrument_id: str = "",
        timeout: float = 30.0,
    ) -> dict[str, OrderField]:
        """查询报单."""
        req = CThostFtdcQryOrderField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        req.InstrumentID = instrument_id

        event_key = f"order_{instrument_id}"
        self.query_events[event_key] = threading.Event()

        # 清空之前的订单数据，确保获取最新状态
        if not instrument_id:  # 查询所有订单时清空
            self.orders.clear()

        self.api.ReqQryOrder(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            timeout,
            f"查询报单超时({timeout:.1f}秒)",
            stop_event=self.stop_event,
        )
        return self.orders

    def OnRspQryOrder(self, pOrder, pRspInfo, _nRequestID, bIsLast):
        """查询报单响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"查询报单失败: {pRspInfo.ErrorMsg}")

        elif pOrder:
            # 转换为Pydantic模型进行状态检查
            order_model = CtpConverter.order_to_model(pOrder)

            # 订单过滤：只保留有效订单，过滤掉已撤销或已完成或已过期的订单
            if self._should_keep_order(order_model):
                order_key = (
                    pOrder.OrderSysID if pOrder.OrderSysID else f"{pOrder.OrderRef}_{pOrder.FrontID}_{pOrder.SessionID}"
                )
                self.orders[order_key] = order_model
                if self.is_active_order(order_model):
                    self.logger.info(f"📋 保留订单: {order_model}")

        if bIsLast:
            self.logger.info(f"订单查询完成，共查询到 {len(self.orders)} 个订单")
            for key in list(self.query_events.keys()):
                if key.startswith("order"):
                    self.query_events[key].set()

    def _query_trades_impl(self, instrument_id: str = "") -> dict[str, TradeField]:
        """执行原生成交查询，不做账户控制记账."""
        req = CThostFtdcQryTradeField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        req.InstrumentID = instrument_id

        event_key = f"trade_{instrument_id}"
        self.query_events[event_key] = threading.Event()
        self.api.ReqQryTrade(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            30,
            "查询成交超时",
            stop_event=self.stop_event,
        )
        return self.trades

    def OnRspQryTrade(self, pTrade, pRspInfo, _nRequestID, bIsLast):
        """查询成交响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"查询成交失败: {pRspInfo.ErrorMsg}")

        elif pTrade:
            # 转换为Pydantic模型
            trade_model = CtpConverter.trade_to_model(pTrade)

            # 仅保留指定时间之后的成交
            trade_time = f"{trade_model.TradeDate} {trade_model.TradeTime}"
            if pd.to_datetime(trade_time) > self._start_time:
                self.trades[pTrade.TradeID] = trade_model
                self.logger.info(f"✅ 新成交: {str(trade_model)}")

        if bIsLast:
            self.logger.info(f"成交查询完成，共查询到 {len(self.trades)} 个成交")
            for key in list(self.query_events.keys()):
                if key.startswith("trade"):
                    self.query_events[key].set()

    # ---- 结算单 ----------------------------------------------------------

    @controlled_operation(
        "query_settlement_info",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="fetched",
    )
    @handle_ctp_error
    def query_settlement_info(self, trading_day=""):
        """查询结算单信息."""
        req = CThostFtdcQrySettlementInfoField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        req.AccountID = ""
        req.CurrencyID = "CNY"
        req.TradingDay = trading_day  # 空表示当前交易日

        # 初始化结算单内容存储
        self.settlement_content = []

        event_key = f"settlement_{trading_day}"
        self.query_events[event_key] = threading.Event()
        self.api.ReqQrySettlementInfo(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            30,
            "查询结算单超时",
            stop_event=self.stop_event,
        )

        # 合并所有结算单内容
        if self.settlement_content:
            str_contents = [_safe_decode_content(item) for item in self.settlement_content]
            full_content = "\n".join(str_contents)
        else:
            full_content = ""

        return full_content

    def OnRspQrySettlementInfo(self, pSettlementInfo, pRspInfo, _nRequestID, bIsLast):
        """查询结算单响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"查询结算单失败: {pRspInfo.ErrorMsg}")
        elif pSettlementInfo and pSettlementInfo.Content:
            # 使用安全解码函数处理内容
            content = _safe_decode_content(pSettlementInfo.Content).strip()
            if content:
                self.settlement_content.append(content)

        if bIsLast:
            self.logger.info(f"结算单查询完成，共收到 {len(self.settlement_content)} 个片段")
            for key in list(self.query_events.keys()):
                if key.startswith("settlement"):
                    self.query_events[key].set()

    def _display_settlement_info(self, settlement_content: str | bytes):
        """展示结算单详情."""
        if not settlement_content:
            self.logger.warning("⚠️  结算单内容为空")
            return

        self.logger.info("📋 结算单详情:")
        self.logger.info("=" * 60)

        try:
            # 使用安全解码函数处理内容
            settlement_content = _safe_decode_content(settlement_content)

            # 处理编码问题，确保能正确显示中文
            lines = settlement_content.split("\n")
            displayed_lines = 0
            max_display_lines = 50  # 限制显示行数避免日志过长

            for line in lines:
                if line.strip():
                    clean_line = line.strip().replace("\x00", "").replace("\r", "").replace("\t", " ")
                    if clean_line:
                        clean_line = "".join(char for char in clean_line if ord(char) >= 32 or char in "\n\r\t")
                        if clean_line:
                            self.logger.info(f"  {clean_line}")
                            displayed_lines += 1

                            if displayed_lines >= max_display_lines:
                                remaining_lines = len(lines) - lines.index(line) - 1
                                if remaining_lines > 0:
                                    self.logger.info(f"  ... (还有 {remaining_lines} 行，已省略显示)")
                                break

        except (
            AttributeError,
            KeyError,
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as e:
            self.logger.warning(f"显示结算单时出现问题: {e}")
            try:
                if isinstance(settlement_content, bytes):
                    content_str = settlement_content[:200].decode(errors="ignore")
                else:
                    content_str = str(settlement_content)[:200]
                content_summary = content_str + ("..." if len(settlement_content) > 200 else "")
                self.logger.info(f"  结算单摘要: {content_summary}")
            except (
                AttributeError,
                KeyError,
                LookupError,
                OSError,
                RuntimeError,
                TypeError,
                UnicodeError,
                ValueError,
            ):
                self.logger.info(
                    f"  结算单数据类型: {type(settlement_content)}, 长度: {len(settlement_content) if hasattr(settlement_content, '__len__') else 'unknown'}"
                )

        self.logger.info("=" * 60)
        self.logger.info("📋 结算单显示完成")

    # ---- UnifiedOrder 缓存与回调 -----------------------------------------

    def _find_unified_order(
        self,
        order_ref: str | None = None,
        order_sys_id: str | None = None,
        front_id: int | None = None,
        session_id: int | None = None,
    ) -> UnifiedOrder | None:
        """查找对应的UnifiedOrder."""
        with self._unified_orders_lock:
            # 首先尝试通过OrderSysID查找
            if order_sys_id and order_sys_id in self._unified_orders:
                return self._unified_orders[order_sys_id]

            # 然后尝试通过OrderRef查找（需要front_id和session_id来确保唯一性）
            if order_ref and front_id is not None and session_id is not None:
                for _key, order in self._unified_orders.items():
                    if (
                        order.extra.get("order_ref") == order_ref
                        and order.extra.get("front_id") == front_id
                        and order.extra.get("session_id") == session_id
                    ):
                        return order

            # 最后只通过OrderRef查找（可能不唯一，返回第一个匹配的）
            if order_ref:
                for order in self._unified_orders.values():
                    if order.extra.get("order_ref") == order_ref:
                        return order

        return None

    def get_unified_orders(self) -> list[UnifiedOrder]:
        """获取所有UnifiedOrder."""
        with self._unified_orders_lock:
            return list(self._unified_orders.values())

    def refresh_order_statuses(self, timeout: float = 10.0) -> list[UnifiedOrder]:
        """主动查询报单并同步统一订单状态."""
        orders = self.query_orders(timeout=timeout)
        refreshed_orders: list[UnifiedOrder] = []

        for order_key, order_model in orders.items():
            refreshed_unified = order_model.to_unified()
            unified_order = self._find_unified_order(
                order_ref=getattr(order_model, "OrderRef", None),
                order_sys_id=getattr(order_model, "OrderSysID", None),
                front_id=getattr(order_model, "FrontID", None),
                session_id=getattr(order_model, "SessionID", None),
            )

            with self._unified_orders_lock:
                callback_order: UnifiedOrder
                order_sys_id = getattr(order_model, "OrderSysID", "")
                order_ref = getattr(order_model, "OrderRef", "")

                if unified_order is not None:
                    if order_sys_id and unified_order.order_id == order_ref and order_ref in self._unified_orders:
                        del self._unified_orders[order_ref]
                        self._unified_orders[order_sys_id] = unified_order
                        unified_order.order_id = order_sys_id

                    unified_order.status = refreshed_unified.status
                    unified_order.filled_volume = refreshed_unified.filled_volume
                    unified_order.avg_price = refreshed_unified.avg_price
                    unified_order.extra.update(refreshed_unified.extra)
                    unified_order.update_timestamp = get_default_clock().time()
                    callback_order = unified_order
                else:
                    callback_order = refreshed_unified
                    self._unified_orders[order_key] = callback_order

            self._dispatch_order_callback(callback_order)
            refreshed_orders.append(callback_order)

        return refreshed_orders

    def get_unified_order(self, order_id: str) -> UnifiedOrder | None:
        """根据订单ID获取UnifiedOrder."""
        with self._unified_orders_lock:
            return self._unified_orders.get(order_id)

    # ---- 回调注册 / 分发 -------------------------------------------------

    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        """注册订单更新回调函数."""
        self._callback_manager.register_order_callback(callback)

    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """注册成交记录回调函数."""
        self._callback_manager.register_trade_callback(callback)

    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        """注销订单更新回调函数."""
        self._callback_manager.unregister_order_callback(callback)

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """注销成交记录回调函数."""
        self._callback_manager.unregister_trade_callback(callback)

    def get_callback_count(self) -> dict[str, int]:
        """获取当前注册的回调函数数量."""
        return self._callback_manager.get_callback_count()

    def _dispatch_order_callback(self, order: UnifiedOrder) -> None:
        """分发订单更新回调."""
        self._callback_manager.dispatch_order_callback(order)

    def _dispatch_trade_callback(self, trade: TradeRecord) -> None:
        """分发成交记录回调."""
        self._callback_manager.dispatch_trade_callback(trade)

    # ---- 下单 / 撤单 / 回报 ----------------------------------------------

    @controlled_operation(
        "insert_order",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="submitted",
    )
    @handle_ctp_error
    def insert_order(
        self,
        instrument_id: str,
        direction: DirectionType,
        offset: OffsetFlagType,
        price_type: OrderPriceType,
        limit_price: float,
        volume: int,
        skip_verification: bool = False,
        *,
        trade_rule: dict[str, object] | None = None,
    ) -> str:
        """
        报单（带风控验证）.

        Parameters
        ----------
        instrument_id : str
            合约代码。
        direction : DirectionType
            买卖方向。
        offset : OffsetFlagType
            开平标志。
        price_type : OrderPriceType
            价格类型。
        limit_price : float
            价格。
        volume : int
            数量。
        skip_verification : bool, default=False
            是否跳过验资验仓。
        trade_rule : dict[str, object] | None, optional
            品种交易规则；用于在 CTP 合约表保证金率为 0 时通过
            ``trade_rule['margin_ratio']`` 兜底（典型场景：期权卖方
            合约保证金率未在合约表里配置完整）。算法层在
            ``executor.place_order(... , trade_rule=...)`` 中传入。

        Returns
        -------
        str
            报单引用。
        """
        # 风控验证：验资验仓
        if not skip_verification:
            is_valid, error_msg = self.verify_insert_order(
                instrument_id, direction, offset, limit_price, volume, trade_rule=trade_rule
            )
            if not is_valid:
                self.logger.error(f"🚫 风控拒绝下单：{error_msg}")
                raise ValueError(f"风控验证失败：{error_msg}")

        # 记录操作和更新时间戳
        self._record_operation("order")
        self.last_order_time = get_default_clock().time()

        req = CThostFtdcInputOrderField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        req.UserID = self.user
        req.ExchangeID = ""  # 自动识别
        req.InstrumentID = instrument_id
        req.Direction = direction
        req.CombOffsetFlag = offset
        req.CombHedgeFlag = THOST_FTDC_HF_Speculation
        req.OrderPriceType = price_type
        req.LimitPrice = limit_price
        req.VolumeTotalOriginal = volume
        req.TimeCondition = THOST_FTDC_TC_GFD
        req.VolumeCondition = THOST_FTDC_VC_AV
        req.MinVolume = 1
        req.ContingentCondition = THOST_FTDC_CC_Immediately
        req.ForceCloseReason = THOST_FTDC_FCC_NotForceClose
        req.OrderRef = str(self.order_ref)

        order_ref_str = str(self.order_ref)
        self.order_ref += 1

        self.api.ReqOrderInsert(req, 0)

        # 创建对应的UnifiedOrder
        direction_map = {THOST_FTDC_D_Buy: "买入", THOST_FTDC_D_Sell: "卖出"}
        offset_map = {
            THOST_FTDC_OF_Open: "开仓",
            THOST_FTDC_OF_Close: "平仓",
            THOST_FTDC_OF_CloseToday: "平今",
            THOST_FTDC_OF_CloseYesterday: "平昨",
        }

        direction_desc = direction_map.get(direction, "未知")
        offset_desc = offset_map.get(offset, "未知")

        # 转换为 UnifiedOrder 需要的标准枚举值
        unified_direction = OrderDirection.BUY.value if direction == THOST_FTDC_D_Buy else OrderDirection.SELL.value
        unified_order_type = (
            OrderType.LIMIT.value if price_type == THOST_FTDC_OPT_LimitPrice else OrderType.MARKET.value
        )

        with self._unified_orders_lock:
            # 创建UnifiedOrder，此时还没有OrderSysID，使用order_ref作为临时ID
            self._unified_orders[order_ref_str] = UnifiedOrder.create(
                order_id=order_ref_str,  # 临时ID，收到OnRtnOrder时更新
                symbol=instrument_id,
                direction=unified_direction,
                order_type=unified_order_type,
                volume=float(volume),
                price=float(limit_price),
                channel_type=TradeChannel.CTP,
                status="已报",
                extra={
                    "order_ref": order_ref_str,
                    "front_id": self.front_id,
                    "session_id": self.session_id,
                    "direction": direction,
                    "offset": offset,
                    "price_type": price_type,
                },
            )

        self.logger.warning(
            f"📤 发送报单: {instrument_id} {direction_desc}{offset_desc} {volume}手@{limit_price} (引用={order_ref_str})"
        )

        # 如果是开仓，记录所需保证金
        if offset == THOST_FTDC_OF_Open:
            required_margin = self.calculate_required_margin(
                instrument_id, direction, limit_price, volume, trade_rule=trade_rule
            )
            self.logger.info(f"   预计占用保证金: {required_margin:,.2f}元")

        return order_ref_str

    def OnRspOrderInsert(self, _pInputOrder, pRspInfo, _nRequestID, _bIsLast):
        """报单响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"报单失败: {pRspInfo.ErrorMsg}")

    @safe_callback(log_traceback=True)
    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, _nRequestID, _bIsLast):
        """撤单响应 - 完整版."""
        # 构建唯一标识来查找对应的撤单请求
        order_sys_id = ""
        order_ref = ""
        if pInputOrderAction:
            order_sys_id = getattr(pInputOrderAction, "OrderSysID", "") or ""
            order_ref = getattr(pInputOrderAction, "OrderRef", "") or ""

        # 查找对应的撤单请求
        found = self._cancel_order_manager.find_request(
            order_sys_id=order_sys_id,
            order_ref=order_ref,
        )

        # 处理响应
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = pRspInfo.ErrorMsg or "未知错误"
            self.logger.warning(f"❌ 撤单响应错误: {error_msg} (ErrorID={pRspInfo.ErrorID})")

            if found:
                request_id, _cancel_request = found
                self._cancel_order_manager.update_status(
                    request_id=request_id,
                    status=CancelOrderStatusType.REJECTED,
                    error_code=pRspInfo.ErrorID,
                    error_msg=error_msg,
                )
        else:
            self.logger.info("✅ 撤单请求已接受")

            if found:
                request_id, _cancel_request = found
                self._cancel_order_manager.update_status(
                    request_id=request_id,
                    status=CancelOrderStatusType.ACCEPTED,
                )
            else:
                self.logger.warning("⚠️  无法找到对应的撤单请求记录")

        if pInputOrderAction:
            self.logger.debug(
                f"撤单响应详情: OrderSysID={pInputOrderAction.OrderSysID}, "
                f"OrderRef={pInputOrderAction.OrderRef}, "
                f"InstrumentID={getattr(pInputOrderAction, 'InstrumentID', '')}"
            )

    @safe_callback(log_traceback=True)
    def OnErrRtnOrderAction(self, pOrderAction, pRspInfo):
        """撤单错误回报 - 完整版."""
        if not pRspInfo:
            self.logger.warning("收到撤单错误回报但无错误信息")
            return

        error_msg = pRspInfo.ErrorMsg or "未知错误"
        error_code = pRspInfo.ErrorID

        self.logger.warning(f"💥 撤单错误回报: {error_msg} (ErrorID={error_code})")

        order_sys_id = ""
        order_ref = ""
        if pOrderAction:
            order_sys_id = getattr(pOrderAction, "OrderSysID", "") or ""
            order_ref = getattr(pOrderAction, "OrderRef", "") or ""

        found = self._cancel_order_manager.find_request(
            order_sys_id=order_sys_id,
            order_ref=order_ref,
        )

        if found:
            request_id, cancel_request = found
            self._cancel_order_manager.update_status(
                request_id=request_id,
                status=CancelOrderStatusType.FAILED,
                error_code=error_code,
                error_msg=error_msg,
            )
            self.logger.warning(f"📋 撤单请求 {cancel_request.instrument_id} 状态已更新: FAILED")
        else:
            self.logger.warning("⚠️  撤单错误回报：无法找到对应的撤单请求记录")

        if pOrderAction:
            self.logger.debug(
                f"撤单错误详情: OrderSysID={getattr(pOrderAction, 'OrderSysID', '')}, "
                f"OrderRef={getattr(pOrderAction, 'OrderRef', '')}, "
                f"InstrumentID={getattr(pOrderAction, 'InstrumentID', '')}"
            )

    @safe_callback(log_traceback=True)
    def OnRtnOrderAction(self, pOrderAction):
        """撤单回报 - 完整版."""
        if not pOrderAction:
            self.logger.warning("收到撤单回报但无回报数据")
            return

        order_sys_id = getattr(pOrderAction, "OrderSysID", "")
        order_ref = getattr(pOrderAction, "OrderRef", "")
        instrument_id = getattr(pOrderAction, "InstrumentID", "")
        exchange_id = getattr(pOrderAction, "ExchangeID", "")

        self.logger.info(
            f"🎉 撤单成功回报: {instrument_id}@{exchange_id} OrderSysID={order_sys_id}, OrderRef={order_ref}"
        )

        found = self._cancel_order_manager.find_request(
            order_sys_id=order_sys_id,
            order_ref=order_ref,
        )

        if found:
            request_id, cancel_request = found
            self._cancel_order_manager.update_status(
                request_id=request_id,
                status=CancelOrderStatusType.SUCCESS,
            )
            self.logger.info(f"✅ 撤单请求 {cancel_request.instrument_id} 状态已更新: SUCCESS")
        else:
            self.logger.warning("⚠️  撤单成功回报：无法找到对应的撤单请求记录")

        self.logger.debug(
            f"撤单成功详情: OrderSysID={order_sys_id}, "
            f"OrderRef={order_ref}, InstrumentID={instrument_id}, "
            f"ExchangeID={exchange_id}"
        )

    def OnRtnOrder(self, pOrder):
        """报单回报."""
        if pOrder:
            order_model = CtpConverter.order_to_model(pOrder)

            order_key = (
                pOrder.OrderSysID if pOrder.OrderSysID else f"{pOrder.OrderRef}_{pOrder.FrontID}_{pOrder.SessionID}"
            )
            self.orders[order_key] = order_model

            callback_order: UnifiedOrder | None = None

            with self._unified_orders_lock:
                unified_order = self._find_unified_order(
                    order_ref=pOrder.OrderRef,
                    order_sys_id=pOrder.OrderSysID,
                    front_id=pOrder.FrontID,
                    session_id=pOrder.SessionID,
                )

                if unified_order:
                    if pOrder.OrderSysID and unified_order.order_id == pOrder.OrderRef:
                        del self._unified_orders[pOrder.OrderRef]
                        self._unified_orders[pOrder.OrderSysID] = unified_order
                        unified_order.order_id = pOrder.OrderSysID

                    unified_order.status = order_model.to_unified().status
                    unified_order.filled_volume = float(order_model.VolumeTraded)
                    unified_order.extra.update(
                        {
                            "volume_left": float(order_model.VolumeTotal),
                            "status_msg": order_model.StatusMsg or "",
                            "update_time": order_model.UpdateTime,
                            "cancel_time": order_model.CancelTime,
                        }
                    )

                    unified_order.update_timestamp = get_default_clock().time()
                    callback_order = unified_order
                else:
                    callback_order = order_model.to_unified()
                    self._unified_orders[order_key] = callback_order

            if callback_order:
                self._dispatch_order_callback(callback_order)

            self.logger.warning(f"🔔 报单回报: \n{order_model}")

            if order_model.StatusMsg:
                self.logger.warning(f"   状态消息: {order_model.StatusMsg}")

            terminal_states = {
                OrderStatusType.ALL_TRADED,
                OrderStatusType.CANCELED,
                OrderStatusType.PART_TRADED_NOT_QUEUEING,
                OrderStatusType.NO_TRADE_NOT_QUEUEING,
            }

            if order_model.OrderStatus in terminal_states:
                self.logger.warning(f"   订单完成: {order_model.InsertTime} -> {order_model.UpdateTime}")

    def OnRtnTrade(self, pTrade):
        """成交回报."""
        if pTrade:
            trade_model = CtpConverter.trade_to_model(pTrade)
            self.trades[pTrade.TradeID] = trade_model

            callback_trade: TradeRecord | None = None

            with self._unified_orders_lock:
                unified_order = self._find_unified_order(
                    order_ref=pTrade.OrderRef,
                    order_sys_id=pTrade.OrderSysID,
                    front_id=getattr(pTrade, "FrontID", None),
                    session_id=getattr(pTrade, "SessionID", None),
                )

                if unified_order:
                    trade_record = trade_model.to_unified_trade()
                    callback_trade = trade_record

                    self.logger.info(f"   更新UnifiedOrder成交记录: {trade_record}")

            if callback_trade:
                self._dispatch_trade_callback(callback_trade)

            self.logger.warning(f"💰 成交回报:\n{trade_model}")

    def get_account_summary(self) -> dict[str, Any]:
        """获取账户摘要信息."""
        if not self.account:
            return {}

        return {
            "account_id": self.account.AccountID,
            "available": self.account.Available,
            "balance": self.account.Balance,
            "margin": self.account.CurrMargin,
            "position_profit": self.account.PositionProfit,
            "close_profit": self.account.CloseProfit,
            "commission": self.account.Commission,
            "trading_day": self.account.TradingDay,
        }

    def log_current_status(self):
        """记录当前状态概览."""
        self.logger.info("=" * 50)
        self.logger.info("CTP客户端当前状态概览")
        self.logger.info("=" * 50)

        self.logger.info(
            f"连接状态: 连接={self.connected}, 认证={self.authenticated}, "
            f"登录={self.logged_in}, 结算确认={self.settlement_confirmed}"
        )

        if self.account:
            account_info = self.get_account_summary()
            self.logger.info(
                f"账户信息: ID={account_info['account_id']}, "
                f"可用资金={account_info['available']:,.2f}, "
                f"持仓盈亏={account_info['position_profit']:,.2f}"
            )

        positions = self.get_positions_summary()
        if positions:
            self.logger.info(f"持仓数量: {len(positions)}个")
            for pos in positions[:5]:
                self.logger.info(
                    f"  {pos['instrument_id']} {pos['net_position']}手, 盈亏={pos['total_position_profit']:,.2f}"
                )
        else:
            self.logger.info("持仓数量: 0个")

        active_orders = [o for o in self.orders.values() if self.is_active_order(o)]
        if active_orders:
            self.logger.info(f"活跃订单: {len(active_orders)}个")
            for order in active_orders[:5]:
                self.logger.info(f"\n{order}")
        else:
            self.logger.info("活跃订单: 0个")

        self.logger.info("=" * 50)

    # ---- 撤单 -------------------------------------------------------------

    def cancel_order(self, order: OrderField, method: str = "auto") -> bool:
        """
        撤单方法 - 支持自动选择撤单方式.

        根据订单信息自动选择最佳的撤单方法.

        Notes
        -----
        ``cancel_order`` 操作的限流由 ``AbstractExecutorFacadeMixin.cancel_order``
        上的 ``@controlled_operation('cancel_order')`` 装饰器在 facade 层
        统一计账。trader 层不重复挂同名装饰器（会引发 registry 冲突），
        因此从 ``cancel_all_orders`` 等 trader 内部路径绕过 facade 的批量
        撤单调用不会被 guard 记账；该路径属于会话清理时的低频补救动作，
        风险较低。如需更严格的 CTP-API 级保护，可在后续 sprint 中引入
        独立的 ``ctp_cancel_order_native`` operation key 并扩展 preset。

        Parameters
        ----------
        order : OrderField
            订单对象。
        method : str, default="auto"
            撤单方法，支持 ``"method1"``、``"method2"`` 和 ``"auto"``。

        Returns
        -------
        bool
            撤单请求是否发送成功。
        """
        try:
            req = CThostFtdcInputOrderActionField()
            req.BrokerID = self.broker
            req.InvestorID = self.user
            req.UserID = self.user
            req.ActionFlag = THOST_FTDC_AF_Delete

            if method == "auto":
                if order.OrderSysID:
                    method = "method1"
                elif (
                    order.OrderRef
                    and getattr(order, "FrontID", None) is not None
                    and getattr(order, "SessionID", None) is not None
                ):
                    method = "method2"
                else:
                    self.logger.error("❌ 撤单失败：订单缺少必要的撤单参数")
                    return False

            if method.lower() == "method1":
                if not order.OrderSysID or not order.OrderSysID.strip():
                    self.logger.error("❌ 撤单失败：OrderSysID不能为空")
                    return False

                req.OrderSysID = order.OrderSysID
                req.ExchangeID = order.ExchangeID
                req.InstrumentID = order.InstrumentID

                result = self.api.ReqOrderAction(req, 0)

                if result == 0:
                    self._cancel_order_manager.create_request(
                        order_sys_id=order.OrderSysID,
                        order_ref=getattr(order, "OrderRef", "") or "",
                        exchange_id=order.ExchangeID,
                        instrument_id=order.InstrumentID,
                    )
                    self.logger.info(
                        f"📤 撤单请求[方法1-推荐]已发送: {order.InstrumentID}@{order.ExchangeID} 系统编号={order.OrderSysID}"
                    )
                    return True
                else:
                    self.logger.error(f"❌ 撤单请求[方法1]发送失败: API返回码={result}")
                    return False

            elif method.lower() == "method2":
                if not order.OrderRef:
                    self.logger.error("❌ 撤单失败：OrderRef不能为空")
                    return False

                if not order.InstrumentID:
                    self.logger.error("❌ 撤单失败：方法2必须提供InstrumentID合约代码")
                    return False

                req.OrderRef = str(order.OrderRef)
                req.FrontID = order.FrontID
                req.SessionID = order.SessionID
                req.InstrumentID = order.InstrumentID
                req.ExchangeID = order.ExchangeID

                result = self.api.ReqOrderAction(req, 0)

                if result == 0:
                    self._cancel_order_manager.create_request(
                        order_sys_id=getattr(order, "OrderSysID", "") or "",
                        order_ref=order.OrderRef,
                        exchange_id=order.ExchangeID,
                        instrument_id=order.InstrumentID,
                    )
                    self.logger.info(
                        f"📤 撤单请求[方法2]已发送: {order.InstrumentID}@{order.ExchangeID} "
                        f"引用={order.OrderRef} 前置={order.FrontID} 会话={order.SessionID}"
                    )
                    return True
                else:
                    self.logger.error(f"❌ 撤单请求[方法2]发送失败: API返回码={result}")
                    return False
            else:
                self.logger.error(f"❌ 撤单失败：不支持的方法 '{method}'，仅支持 'method1', 'method2' 或 'auto'")
                return False

        except CTP_COMMON_EXCEPTIONS as e:
            self.logger.error(f"❌ 撤单请求[{method}]异常: {e}，订单详情：{order}")
            return False

    def is_active_order(self, order: OrderField) -> bool:
        """判断订单是否为活跃订单."""
        return order.OrderStatus in [
            OrderStatusType.PART_TRADED_QUEUEING,
            OrderStatusType.NO_TRADE_QUEUEING,
        ]

    def cancel_all_orders(
        self,
        filter_func: Callable[[Any], bool] | None = None,
        use_flow_control: bool = True,
    ) -> dict[str, Any]:
        """
        批量撤单 - 撤销所有活跃订单.

        Parameters
        ----------
        filter_func : Callable[[Any], bool] | None, optional
            过滤函数，用于筛选需要撤销的订单。
        use_flow_control : bool, default=True
            已废弃，保留参数仅为兼容旧调用方。

        Returns
        -------
        dict[str, Any]
            撤单结果统计信息。
        """
        try:
            _ = use_flow_control
            self.logger.info("🔍 开始批量撤单，先查询当前订单...")
            orders = self.query_orders()

            if not orders:
                self.logger.info("✅ 没有发现任何订单，无需撤单")
                return {
                    "total_orders": 0,
                    "active_orders": 0,
                    "cancel_attempted": 0,
                    "cancel_success": 0,
                    "cancel_failed": 0,
                    "success_rate": 0.0,
                }

            active_orders = []
            for _order_key, order in orders.items():
                if self.is_active_order(order):
                    if filter_func is None or filter_func(order):
                        active_orders.append(order)

            self.logger.info(f"📊 订单统计: 总订单 {len(orders)} 个，活跃订单 {len(active_orders)} 个")

            if not active_orders:
                self.logger.info("✅ 没有发现活跃订单，无需撤单")
                return {
                    "total_orders": len(orders),
                    "active_orders": 0,
                    "cancel_attempted": 0,
                    "cancel_success": 0,
                    "cancel_failed": 0,
                    "success_rate": 0.0,
                }

            cancel_attempted = 0
            cancel_success = 0
            cancel_failed = 0

            self.logger.warning(f"🔄 开始撤销 {len(active_orders)} 个活跃订单...")

            for i, order in enumerate(active_orders, 1):
                try:
                    self.logger.info(
                        f"📤 撤单进度 [{i}/{len(active_orders)}]: {order.InstrumentID} "
                        f"系统编号={order.OrderSysID or '空'} 引用={order.OrderRef}"
                    )

                    cancel_attempted += 1

                    success = self.cancel_order(order, method="auto")

                    if success:
                        cancel_success += 1
                        self.logger.info(f"✅ 撤单成功: {order.InstrumentID}")
                    else:
                        cancel_failed += 1
                        self.logger.warning(f"❌ 撤单失败: {order.InstrumentID}")

                except CTP_COMMON_EXCEPTIONS as e:
                    cancel_failed += 1
                    self.logger.error(f"❌ 撤单异常: {order.InstrumentID} - {e}")

            success_rate = (cancel_success / max(1, cancel_attempted)) * 100

            result = {
                "total_orders": len(orders),
                "active_orders": len(active_orders),
                "cancel_attempted": cancel_attempted,
                "cancel_success": cancel_success,
                "cancel_failed": cancel_failed,
                "success_rate": success_rate,
            }

            self.logger.warning("=" * 60)
            self.logger.warning("🎯 批量撤单完成")
            self.logger.warning("=" * 60)
            self.logger.info(f"📊 总订单数: {result['total_orders']}")
            self.logger.info(f"🔄 活跃订单: {result['active_orders']}")
            self.logger.info(f"📤 尝试撤单: {result['cancel_attempted']}")
            self.logger.info(f"✅ 成功撤单: {result['cancel_success']}")
            self.logger.info(f"❌ 失败撤单: {result['cancel_failed']}")
            self.logger.info(f"📈 成功率: {result['success_rate']:.1f}%")
            self.logger.warning("=" * 60)

            return result

        except CTP_COMMON_EXCEPTIONS as e:
            self.logger.error(f"❌ 批量撤单过程中发生异常: {e}")
            import traceback

            self.logger.error(f"异常详情: {traceback.format_exc()}")
            return {
                "total_orders": 0,
                "active_orders": 0,
                "cancel_attempted": 0,
                "cancel_success": 0,
                "cancel_failed": 0,
                "success_rate": 0.0,
                "error": str(e),
            }

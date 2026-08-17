"""
QMT 交易执行器实现.

提供基于 ``AbstractExecutor`` 架构的 QMT 执行器、行情辅助函数，以及与 QMT
桌面端和 XtQuant 接口相关的执行逻辑。
"""

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownVariableType=false
# pyright: reportReturnType=false
# pyright: reportMissingTypeStubs=false
# pyright: reportMissingModuleSource=false

from datetime import datetime, timedelta
from typing import Any, cast, override

import loguru

# XTQuant 是第三方交易 API，未提供类型桩
from xtquant import xtdata  # type: ignore
from xtquant.xttrader import XtQuantTrader  # type: ignore
from xtquant.xttype import (  # type: ignore
    StockAccount,  # type: ignore
    XtAsset,
    XtPosition,
)

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.algorithms.core.base import LoggerProtocol

# 公共函数
from axile.executor.common_functions import is_trading_time

# 统一模型
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_callback import (
    OrderUpdateCallback,
    PriceDataCallback,
    TradeRecordCallback,
    UnifiedCallbackClient,
)
from axile.executor.models.unified_input import AccountConfig, QMTAccountConfig
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData

# 数据转换器
from axile.executor.qmt.converters.order_converter import (
    convert_qmt_order_to_unified,
    convert_qmt_trade_to_trade_record,
)
from axile.executor.qmt.converters.price_converter import convert_qmt_tick_to_unified_price
from axile.executor.qmt.core.callback_dispatcher import QMTCallbackDispatcher
from axile.executor.qmt.core.qmt_callback import QMTTraderCallback

# QMT 核心组件
from axile.executor.qmt.core.qmt_client import (
    close_exe_window,
    find_exe_window,
    initialize_qmt,
    start_qmt_exe,
    wait_qmt_ready,
)

__all__ = [
    "QMTExecutor",
    "close_exe_window",
    "find_exe_window",
    "get_ticks",
    "initialize_qmt",
    "start_qmt_exe",
    "wait_qmt_ready",
]


# ==================================================================================================
# 交易辅助函数
# ==================================================================================================


def get_ticks(symbols: list[str], **kwargs: object) -> dict[str, UnifiedPriceData]:
    """
    获取最新 tick，并转换为统一价格模型.

    Parameters
    ----------
    symbols : list[str]
        需要拉取行情的品种代码列表。
    **kwargs : object
        额外参数；支持通过 ``logger`` 传入日志对象。

    Returns
    -------
    dict[str, UnifiedPriceData]
        品种代码到 ``UnifiedPriceData`` 的映射。
    """
    logger = cast("LoggerProtocol", kwargs.get("logger", loguru.logger))

    logger.warning(f"get_ticks - xtdata 数据路径：{xtdata.data_dir}")
    ticks = xtdata.get_full_tick(symbols)

    res = {}
    for symbol, tick in ticks.items():
        res[symbol] = convert_qmt_tick_to_unified_price(symbol, tick)

    return res


# ==================================================================================================
# QMT 执行器
# ==================================================================================================


class QMTExecutor(AbstractExecutor, UnifiedCallbackClient):
    """
    QMT 交易执行器.

    Notes
    -----
    该执行器继承 ``AbstractExecutor`` 并实现 ``UnifiedCallbackClient``，
    提供 QMT 渠道下单、查询、回调分发和执行期共享查询快照集成能力。
    """

    def __init__(self, account_config: QMTAccountConfig) -> None:
        """
        初始化 QMT 执行器.

        Parameters
        ----------
        account_config : QMTAccountConfig
            QMT 账户配置，包含登录和连接所需信息。
        """
        super().__init__(TradeChannel.QMT, account_config)
        self.xtt: XtQuantTrader | None = None  # QMT交易接口实例
        self.acc: StockAccount | None = None  # QMT账户实例
        self.mini_qmt_dir: str  # QMT数据目录路径

        self.logger = loguru.logger

        # 回调组件
        self._callback_dispatcher = QMTCallbackDispatcher()
        self._trader_callback: QMTTraderCallback | None = None
        self._monitoring = False
        self._register_execution_query_runtime_callback_observers()

    # ==================== 实现抽象方法 ====================

    @override
    def _initialize_connection(self, account_config: AccountConfig) -> None:
        """初始化并建立 QMT 连接."""
        if not isinstance(account_config, QMTAccountConfig):
            raise TypeError(f"account_config must be QMTAccountConfig, got {type(account_config)}")
        self.account_config = account_config
        qmt_config: QMTAccountConfig = account_config
        logger = self.logger

        # 如果提供了窗口标题，检查并启动QMT桌面端（如果需要）
        if qmt_config.窗口标题 and qmt_config.窗口标题 != "":
            if not find_exe_window(qmt_config.窗口标题, logger=logger):
                logger.info("QMT桌面端未运行，正在启动...")
                start_qmt_exe(
                    acc=qmt_config.账号,
                    pwd=qmt_config.密码,
                    qmt_exe=qmt_config.应用路径,
                    title=qmt_config.窗口标题,
                    wait_seconds=10,
                    logger=logger,
                )
            else:
                logger.info("QMT桌面端已运行")
        else:
            logger.info("未提供窗口标题，跳过桌面端启动检查")

        # 创建回调处理器
        self._trader_callback = QMTTraderCallback(
            callback_dispatcher=self._callback_dispatcher,
            logger=logger,
        )

        # 初始化连接（传入回调处理器）
        self.xtt, self.acc = initialize_qmt(
            callback=self._trader_callback,
            mini_qmt_dir=qmt_config.数据路径,
            account_id=qmt_config.账号,
            session_id=qmt_config.会话ID,
            logger=logger,
        )

        self.mini_qmt_dir = qmt_config.数据路径
        self._monitoring = True
        logger.info(f"QMT连接成功 - 账户: {qmt_config.账号}")

    @override
    def _verify_connection(self) -> bool:
        """验证 QMT 连接是否有效."""
        try:
            # 检查连接状态
            if self.xtt is None:
                return False
            return self.xtt.connected
        except Exception:
            return False

    @override
    def _check_trading_time(self) -> bool:
        """检查是否在股票交易时间."""
        return is_trading_time()

    @override
    def get_account_assets(self) -> UnifiedAccountAssets:
        """获取账户资产并转换为统一格式（公开 API）."""
        return self._get_account_assets_impl()

    @override
    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        """获取市场数据（公开 API）."""
        if not symbols:
            return {}

        self.logger.info(f"获取 {len(symbols)} 个品种的价格数据")
        return get_ticks(symbols, logger=self.logger)

    def _query_order_records(self, *, cancelable_only: bool) -> list[UnifiedOrder]:
        """查询账户级订单并转换为统一 UnifiedOrder 列表."""
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        order_records: list[UnifiedOrder] = []
        for qmt_order in self.xtt.query_stock_orders(self.acc, cancelable_only=cancelable_only) or []:
            order_records.append(convert_qmt_order_to_unified(qmt_order))
        return order_records

    def _query_trade_records(self) -> list[TradeRecord]:
        """查询账户级成交并转换为统一 TradeRecord 列表."""
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        trade_records: list[TradeRecord] = []
        for trade in self.xtt.query_stock_trades(self.acc) or []:
            trade_record = convert_qmt_trade_to_trade_record(trade)
            trade_record.extra = {
                **trade_record.extra,
                "symbol": getattr(trade, "stock_code", ""),
                "order_id": str(getattr(trade, "order_id", "") or ""),
                "order_sysid": str(getattr(trade, "order_sysid", "") or ""),
            }
            trade_records.append(trade_record)
        return trade_records

    def _submit_stock_order(
        self,
        *,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float,
        strategy_name: str,
        order_remark: str,
    ) -> int:
        """执行纯 QMT 下单请求，不处理账户控制."""
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")
        return self.xtt.order_stock(
            account=self.acc,
            stock_code=stock_code,
            order_type=order_type,
            order_volume=order_volume,
            price_type=price_type,
            price=price,
            strategy_name=strategy_name,
            order_remark=order_remark,
        )

    def _submit_cancel_order(self, *, order_id: int) -> int:
        """执行纯 QMT 撤单请求，不处理账户控制."""
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")
        return self.xtt.cancel_order_stock(self.acc, order_id)

    @override
    def _place_order_impl(
        self,
        symbol: str,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0,
        **kwargs: object,
    ) -> UnifiedOrder:
        """下单并返回统一订单模型."""
        # 下单
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        order_id = self.send_stock_order(
            stock_code=symbol,
            direction=direction,
            order_type=order_type,
            order_volume=int(volume),
            price=price,
        )

        if order_id == -1:
            raise RuntimeError(f"下单失败: {symbol} {direction} {volume}")

        # 创建并返回UnifiedOrder
        unified_order = UnifiedOrder.create(
            order_id=str(order_id),
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            volume=float(volume),
            price=price,
            status="已报",
            create_time=datetime.now().isoformat(),
            channel_type=TradeChannel.QMT,
        )

        self.logger.info(f"下单成功: {symbol} {direction} {volume}股 @ {price}")
        return unified_order

    @override
    def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
        """获取未完成订单列表（公开 API）."""
        if self.xtt is None or self.acc is None:
            return []

        pending_orders = self._query_order_records(cancelable_only=True)
        if symbol is None:
            return pending_orders
        return [order for order in pending_orders if order.symbol == symbol]

    @override
    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        """获取指定订单的成交明细."""
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        matched_trades: list[TradeRecord] = []
        for trade_record in self._query_trade_records():
            if trade_record.symbol != symbol:
                continue

            candidate_ids = {
                trade_record.order_id,
                str(trade_record.extra.get("order_sysid", "") or ""),
            }
            if order_id not in candidate_ids:
                continue

            matched_trades.append(trade_record)

        return matched_trades

    @override
    def _get_execution_pending_orders_snapshot_fetcher(self):
        """返回 Execution 内部共享的账户级挂单 snapshot."""
        return lambda: self._run_execution_shared_fetch(
            operation="query_order",
            shared_query_key=("pending_orders_snapshot",),
            query_scope="snapshot",
            fetcher=lambda: self._query_order_records(cancelable_only=True),
        )

    @override
    def _get_execution_trades_snapshot_fetcher(self):
        """返回 execution 内部共享的账户级成交快照 fetcher."""
        return lambda: self._run_execution_shared_fetch(
            operation="query_trades",
            shared_query_key=("trades_snapshot",),
            query_scope="snapshot",
            fetcher=self._fetch_trade_records_snapshot_for_execution,
        )

    def _fetch_trade_records_snapshot_for_execution(self) -> list[TradeRecord]:
        """将账户级原始成交转成统一快照，并补齐 execution 共享过滤需要的字段."""
        return self._query_trade_records()

    def _register_execution_query_runtime_callback_observers(self) -> None:
        """注册 execution 共享查询失效观察者."""
        if getattr(self, "_execution_query_runtime_observers_registered", False):
            return
        bridge = self.get_execution_query_runtime_bridge()
        self._callback_dispatcher.register_order_observer(bridge.observe_order_update)
        self._callback_dispatcher.register_trade_observer(bridge.observe_trade_record)
        self._execution_query_runtime_observers_registered = True

    @override
    def get_tick_size(self, symbol: str) -> float | None:
        """
        获取 A 股品种的最小价格变动单位.

        Parameters
        ----------
        symbol : str
            品种代码，例如 ``000001.SZ`` 或 ``510300.SH``。

        Returns
        -------
        float | None
            估算得到的最小价格变动单位；异常时回退到默认股票精度。
        """
        try:
            # 提取代码部分（去掉交易所后缀）
            code = symbol.split(".")[0] if "." in symbol else symbol

            # ETF：5 或 51 开头
            if code.startswith("5") or code.startswith("51"):
                return 0.001

            # 可转债：12 开头
            if code.startswith("12"):
                return 0.001

            # 默认股票：0.01 元
            return 0.01

        except Exception as e:
            self.logger.warning(f"获取 {symbol} tick_size 失败: {e}")
            return 0.01  # 默认返回股票精度

    @override
    def _cleanup(self) -> None:
        """清理资源."""
        try:
            # 停止监控
            self._monitoring = False

            if self.xtt and self.xtt.connected:
                # 断开连接
                self.xtt.stop()
                self.logger.info("QMT连接已断开")
        except Exception as e:
            self.logger.error(f"清理QMT连接时出错: {e}")
        finally:
            # 清理实例变量
            self.xtt = None
            self.acc = None
            self._trader_callback = None

    # ==================== 实现 AbstractExecutor 的抽象方法 ====================

    @override
    def _get_account_mark(self) -> str:
        """获取 QMT 账户标识."""
        if not isinstance(self.account_config, QMTAccountConfig):
            raise TypeError("account_config must be QMTAccountConfig")
        return self.account_config.账号

    @override
    def _get_operation_display(self, order: UnifiedOrder) -> str:
        """获取 QMT 的操作类型显示."""
        # 从extra中获取offset_flag
        offset_flag = order.extra.get("offset_flag", 0)

        # 根据offset_flag判断操作类型
        if offset_flag == 48:  # OFFSET_FLAG_OPEN 买入开仓
            return "开多"
        elif offset_flag == 49:  # OFFSET_FLAG_CLOSE 卖出平仓
            return "平多"
        else:
            # 默认显示
            return "买入" if order.direction == OrderDirection.BUY else "卖出"

    @override
    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, Any]:
        """获取清仓时的默认交易规则."""
        # A股的默认交易规则
        default_rules = {}
        for symbol in symbols:
            default_rules[symbol] = {"一手数量": 100}
        return default_rules

    # ==================== 实现 UnifiedCallbackClient 接口 ====================

    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注册订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            符合订单回调协议的可调用对象。
        """
        self._callback_dispatcher.register_order_callback(callback)

    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注册成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            符合成交回调协议的可调用对象。
        """
        self._callback_dispatcher.register_trade_callback(callback)

    def register_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注册价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            符合价格回调协议的可调用对象。
        """
        self._callback_dispatcher.register_price_callback(callback)

    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注销订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            待注销的订单回调函数。
        """
        self._callback_dispatcher.unregister_order_callback(callback)

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注销成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            待注销的成交回调函数。
        """
        self._callback_dispatcher.unregister_trade_callback(callback)

    def unregister_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注销价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            待注销的价格回调函数。
        """
        self._callback_dispatcher.unregister_price_callback(callback)

    def is_monitoring(self) -> bool:
        """
        检查是否正在监控.

        Returns
        -------
        bool
            当前已建立连接且监控开启时返回 ``True``。
        """
        return self._monitoring and self.xtt is not None and self.xtt.connected

    def stop(self) -> None:
        """
        停止回调客户端并清理资源.

        Notes
        -----
        该方法会停止 QMT 连接；停止后如需继续使用回调功能，需要重新初始化执行器。
        """
        self._cleanup()

    def initialize_websocket(self, symbols: list[str] | None = None) -> None:
        """
        初始化 WebSocket 连接.

        Parameters
        ----------
        symbols : list[str] | None, default=None
            需要订阅行情的标的列表；QMT 中不使用该参数。

        Notes
        -----
        QMT 回调在连接建立时自动初始化，此方法保留为空实现以满足统一接口要求。
        """
        # QMT 在连接时自动启用回调，无需额外初始化

    def get_callback_count(self) -> dict[str, int]:
        """
        获取当前注册的回调函数数量.

        Returns
        -------
        dict[str, int]
            包含订单、成交和价格回调数量的字典。
        """
        return self._callback_dispatcher.get_callback_count()

    # ==================== QMT 特有方法 ====================

    def _get_account_assets_impl(self) -> UnifiedAccountAssets:
        """
        获取账户资产并直接返回 ``UnifiedAccountAssets``.

        Returns
        -------
        UnifiedAccountAssets
            统一格式的账户资产信息。

        Raises
        ------
        RuntimeError
            当 QMT 连接尚未建立时抛出。
        ValueError
            当查询账户资产失败时抛出。
        """
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        # 查询资产信息
        assets: XtAsset | None = self.xtt.query_stock_asset(self.acc)

        if assets is None:
            raise ValueError("Failed to query account assets")

        # 查询持仓信息
        positions: list[XtPosition] = self.xtt.query_stock_positions(self.acc)

        # 方向映射
        direction_map = {48: PositionDirection.LONG, 49: PositionDirection.SHORT}

        # 直接构建Position对象列表
        unified_positions = []
        for pos in positions:
            # 只保留有持仓的记录
            if pos.volume != 0:
                unified_positions.append(
                    Position.model_construct(
                        symbol=pos.stock_code,
                        volume=float(pos.volume),
                        available_volume=float(pos.can_use_volume),
                        market_value=float(pos.market_value),
                        direction=direction_map.get(pos.direction, PositionDirection.LONG),
                        avg_price=pos.avg_price,
                        extra={
                            "open_price": pos.open_price,
                            "frozen_volume": pos.frozen_volume,
                            "on_road_volume": pos.on_road_volume,
                            "yesterday_volume": pos.yesterday_volume,
                            "last_price": pos.last_price,
                            "profit_rate": pos.profit_rate,
                            "secu_account": pos.secu_account,
                            "instrument_name": pos.instrument_name,
                            "account_type": pos.account_type,
                            "account_id": pos.account_id,
                        },
                    )
                )

        # 创建UnifiedAccountAssets对象，直接传入Position列表
        unified_assets = UnifiedAccountAssets.create(
            available_cash=float(assets.cash),
            total_asset=float(assets.total_asset),
            positions_data=unified_positions,
            channel_type=TradeChannel.QMT,
            currency="CNY",
        )

        # 添加资产相关的额外信息
        unified_assets.extra.update(
            {
                "frozen_cash": float(assets.frozen_cash),
                "fetch_balance": float(assets.fetch_balance),
                "account_type": assets.account_type,
                "account_id": assets.account_id,
            }
        )

        self.logger.info(f"get_account_assets - 账户资产：{unified_assets}")
        return unified_assets

    def send_stock_order(
        self,
        stock_code: str,
        direction: OrderDirection,
        order_type: OrderType,
        order_volume: int,
        price: float = 0,
        **kwargs: object,
    ) -> int:
        """
        执行股票市场下单.

        Parameters
        ----------
        stock_code : str
            证券代码，例如 ``"600000.SH"``。
        direction : OrderDirection
            买卖方向。
        order_type : OrderType
            订单类型，支持市价或限价。
        order_volume : int
            委托数量。股票以股为单位，ETF 以份为单位，通常需要满足手数约束。
        price : float, default=0
            报价价格；市价单时通常为 ``0``。
        **kwargs : object
            额外参数；支持 ``logger``、``strategy_name``、``order_remark`` 和
            ``min_volume`` 等字段。

        Returns
        -------
        int
            下单请求序号；大于 ``0`` 表示提交成功，``-1`` 表示委托失败。

        Raises
        ------
        RuntimeError
            当 QMT 连接尚未建立时抛出。
        """
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        logger = cast("LoggerProtocol", kwargs.get("logger", self.logger))

        # 转换方向
        qmt_order_type = 23 if direction == OrderDirection.BUY else 24  # 23:买, 24:卖

        # 根据 order_type 决定 QMT 的 price_type
        if order_type == OrderType.MARKET:
            price_type = 5  # 最新价
            order_price = 0
        else:  # LIMIT
            price_type = 11  # 限价
            order_price = price

        strategy_name_raw = kwargs.get("strategy_name", "程序下单")
        order_remark_raw = kwargs.get("order_remark", "程序下单")
        strategy_name = str(strategy_name_raw)
        order_remark = str(order_remark_raw)
        min_volume_raw = kwargs.get("min_volume", None)
        min_volume = int(min_volume_raw) if isinstance(min_volume_raw, (int, float)) else None

        if not self.xtt.connected:
            self.xtt.start()
            self.xtt.connect()
            logger.info("send_stock_order - 交易服务器连接成功")

        if min_volume:
            order_volume = max(int(order_volume // min_volume * min_volume), 0)
            logger.info(f"send_stock_order - 最小交易数量限制，订单数量调整为：{order_volume}")

        _id = self._submit_stock_order(
            stock_code=stock_code,
            order_type=qmt_order_type,
            order_volume=int(order_volume),
            price_type=price_type,
            price=order_price,
            strategy_name=strategy_name,
            order_remark=order_remark,
        )
        logger.info(f"send_stock_order - 下单成功，订单编号：{_id}")
        return _id

    def cancel_timeout_orders(
        self,
        minutes: int = 30,
        symbols: list[str] | None = None,
    ) -> None:
        """
        撤销超时的委托单.

        Parameters
        ----------
        minutes : int, default=30
            超时时间，单位为分钟。
        symbols : list[str] | None, default=None
            指定需要撤销的标的列表；为空时处理全部可撤销委托单。

        Raises
        ------
        RuntimeError
            当 QMT 连接尚未建立时抛出。
        """
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        orders = self._query_order_records(cancelable_only=True)
        if not orders:
            return

        self.logger.info(f"查询到 {len(orders)} 个可撤销的委托单，详情：{orders}")

        for o in orders:
            if symbols and o.symbol not in symbols:
                continue

            if datetime.fromisoformat(o.create_time) < datetime.now() - timedelta(minutes=minutes):
                self._submit_cancel_order(order_id=int(o.order_id))
                self.logger.info(f"撤销超时委托单：{o.order_id}; {o.symbol}; {o.volume}; {o.order_type}")

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        """
        撤销指定订单.

        Parameters
        ----------
        symbol : str
            品种代码。
        order_id : str
            订单标识。

        Returns
        -------
        bool
            撤销成功时返回 ``True``，否则返回 ``False``。
        """
        _ = symbol
        if self.xtt is None or self.acc is None:
            raise RuntimeError("QMT连接未建立")

        try:
            result = self._submit_cancel_order(order_id=int(order_id))
            self.logger.info(f"撤销订单 {order_id} 结果: {result}")
            return result == 0
        except Exception as e:
            self.logger.error(f"撤销订单 {order_id} 失败: {e}")
            return False

    def get_callback_stats(self) -> dict[str, int]:
        """
        获取回调统计信息.

        Returns
        -------
        dict[str, int]
            包含各类回调接收数量的统计字典。
        """
        if self._trader_callback:
            return self._trader_callback.get_stats()
        return {}

    def _handle_qmt_error(self, error: Exception, operation: str) -> None:
        """
        处理 QMT 特定错误.

        Parameters
        ----------
        error : Exception
            捕获到的异常对象。
        operation : str
            当前执行的操作名称。

        Raises
        ------
        Exception
            当错误无法通过重连恢复时继续向上抛出。
        """
        error_msg = f"QMT {operation} 失败: {str(error)}"

        # 根据错误类型进行特殊处理
        if "连接" in str(error):
            self.logger.error(f"QMT连接错误，尝试重新连接: {error}")
            # 尝试重新连接
            try:
                if self.account_config is not None:
                    self._initialize_connection(self.account_config)
            except Exception as reconnect_error:
                self.logger.error(f"重新连接失败: {reconnect_error}")
                raise reconnect_error
        else:
            self.logger.error(error_msg)
            raise error

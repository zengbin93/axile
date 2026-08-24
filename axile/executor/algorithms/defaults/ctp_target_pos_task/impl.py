"""
实现 CTP 渠道的 TARGET-POS-TASK 目标持仓算法。

该模块负责把上层已经规划好的单品种目标净持仓，转换为符合 CTP
昨仓 / 今仓规则的订单序列。它只关心单个 ``symbol`` 的落地执行，
不负责组合级别的目标拆解、权重解释或调度。

Notes
-----
实现刻意保持“先平反向仓，再开同向仓”的顺序，以避免净持仓在执行
过程中先朝错误方向偏离，并尽量保留交易所原生 ``offset_flag`` 语义。
当昨仓 / 今仓精确腿不足时，才退回通用平仓标记作为最后补偿。
"""

from typing import Any, Dict, List, Literal, Tuple

from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.common.params import BaseAlgorithmParams, ChaseParamsMixin
from axile.executor.algorithms.core.base import (
    AlgorithmInput,
    AlgorithmResult,
    ExecutorProtocol,
    OrderDirection,
    OrderType,
    register_algorithm,
)
from axile.executor.algorithms.utils.order_tracker import ChaseConfig, OrderTracker
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_order import UnifiedOrder
from axile.executor.models.unified_price import clone_price_data


class CTPTargetPosTaskParams(BaseAlgorithmParams, ChaseParamsMixin):
    """TARGET-POS-TASK 算法参数."""

    price_strategy: Literal["PASSIVE", "ACTIVE"] = "PASSIVE"
    offset_priority: Literal["昨今", "今昨"] = "昨今"

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        return f"CTPTargetPosTaskParams(max_wait_seconds={self.max_wait_seconds}, chase_enabled={self.chase_enabled})"


# ==================== CTP常量定义 ====================

# CTP买卖方向常量
THOST_FTDC_D_Buy = "0"  # 买入
THOST_FTDC_D_Sell = "1"  # 卖出

# CTP开平标志常量
THOST_FTDC_OF_Open = "0"  # 开仓
THOST_FTDC_OF_Close = "1"  # 平仓（通用）
THOST_FTDC_OF_CloseToday = "3"  # 平今仓
THOST_FTDC_OF_CloseYesterday = "4"  # 平昨仓

# CTP价格类型常量
THOST_FTDC_OPT_LimitPrice = "2"  # 限价


# ==================== CTP持仓数据结构 ====================


class CTPPositionDetail:
    """
    表示单个合约的 CTP 风格持仓拆分结果。

    Attributes
    ----------
    symbol : str
        合约代码。
    long_yesterday : int
        多头昨仓手数。
    long_today : int
        多头今仓手数。
    short_yesterday : int
        空头昨仓手数。
    short_today : int
        空头今仓手数。
    long_total : int
        多头总持仓手数。
    short_total : int
        空头总持仓手数。
    net_position : int
        净持仓手数，按 ``long_total - short_total`` 解释。

    Notes
    -----
    该对象是算法内部的归一化视图，用于屏蔽不同通道实现或历史数据
    结构在字段命名上的差异。实例构建完成后，各字段应保持自洽：
    ``*_total`` 至少覆盖对应的昨仓与今仓之和。
    """

    def __init__(self, symbol: str) -> None:
        """
        初始化某个合约的持仓详情容器。

        Parameters
        ----------
        symbol : str
            合约代码。
        """
        self.symbol = symbol
        self.long_yesterday = 0  # 多头昨仓
        self.long_today = 0  # 多头今仓
        self.short_yesterday = 0  # 空头昨仓
        self.short_today = 0  # 空头今仓
        self.long_total = 0  # 多头总持仓
        self.short_total = 0  # 空头总持仓
        self.net_position = 0  # 净持仓

    def update_from_extra(self, position_extra: Dict[str, Any]) -> None:
        """
        从 ``UnifiedPosition.extra`` 中归一化更新 CTP 持仓字段。

        Parameters
        ----------
        position_extra : Dict[str, Any]
            持仓扩展字段。该映射可能来自不同版本的通道适配层，因此
            字段命名并不完全一致。
        """

        def _get_int(value: Any, default: int = 0) -> int:
            if value is None:
                return default
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _get_first_value(*keys: str) -> object | None:
            for key in keys:
                value = position_extra.get(key)
                if value is not None:
                    return value
            return None

        # 兼容两类字段命名：new(yd/td) 与 legacy(_position/_today_position)。
        self.long_yesterday = _get_int(_get_first_value("long_yd", "long_yd_position"))
        self.short_yesterday = _get_int(_get_first_value("short_yd", "short_yd_position"))

        long_total_raw = _get_first_value("long_total", "long_position")
        short_total_raw = _get_first_value("short_total", "short_position")

        # 某些旧通道只回传总仓和昨仓，不单独给今仓。这里用 total - yesterday
        # 推导今仓，并把结果下限钳在 0，避免脏数据把可平今仓放大成负数。
        self.long_today = _get_int(
            _get_first_value("long_td", "long_today_position"),
            max(_get_int(long_total_raw) - self.long_yesterday, 0) if long_total_raw is not None else 0,
        )
        self.short_today = _get_int(
            _get_first_value("short_td", "short_today_position"),
            max(_get_int(short_total_raw) - self.short_yesterday, 0) if short_total_raw is not None else 0,
        )
        self.long_total = _get_int(long_total_raw, self.long_yesterday + self.long_today)
        self.short_total = _get_int(short_total_raw, self.short_yesterday + self.short_today)
        self.net_position = _get_int(
            _get_first_value("net_position"),
            self.long_total - self.short_total,
        )

    @property
    def total_yesterday(self) -> int:
        """昨仓总量."""
        return self.long_yesterday + self.short_yesterday

    @property
    def total_today(self) -> int:
        """今仓总量."""
        return self.long_today + self.short_today

    @property
    def total_available_close(self) -> int:
        """可平仓总量."""
        return self.total_yesterday + self.total_today

    def __str__(self) -> str:
        """返回持仓对象的调试字符串."""
        return (
            f"CTPPosition({self.symbol}: 多昨{self.long_yesterday} 今{self.long_today}, "
            f"空昨{self.short_yesterday} 今{self.short_today}, 净{self.net_position})"
        )


# ==================== 辅助函数 ====================


def _extract_ctp_position_details(
    account_assets: UnifiedAccountAssets, symbols: List[str]
) -> Dict[str, CTPPositionDetail]:
    """
    从统一账户资产中提取 CTP 风格持仓详情。

    Parameters
    ----------
    account_assets : UnifiedAccountAssets
        当前账户资产快照。
    symbols : List[str]
        需要提取持仓详情的品种列表。

    Returns
    -------
    Dict[str, CTPPositionDetail]
        品种到 CTP 持仓详情的映射。
    """
    position_details: Dict[str, CTPPositionDetail] = {}

    for symbol in symbols:
        detail = CTPPositionDetail(symbol)
        position = account_assets.get_position(symbol)

        if position and hasattr(position, "extra"):
            detail.update_from_extra(position.extra)
        else:
            detail.update_from_extra({})

        position_details[symbol] = detail

    return position_details


def _calculate_order_price(
    market_data: Any | None,
    price_type: str,
    direction: str,
) -> float:
    """
    根据价格策略计算 CTP 下单价格。

    Parameters
    ----------
    market_data : Any | None
        当前品种的市场数据。
    price_type : str
        价格策略，支持 ``PASSIVE`` 和 ``ACTIVE``。
    direction : str
        订单方向，支持 ``BUY`` 和 ``SELL``。

    Returns
    -------
    float
        计算得出的下单价格；缺少行情时返回 ``0`` 以触发下游市价单语义。
    """
    if market_data is None:
        return 0.0  # 市场数据缺失时使用市价单

    price_data = market_data

    # PASSIVE 使用本方最优价等待成交；ACTIVE 使用对手方最优价主动成交。
    if price_type.upper() == "PASSIVE":
        quote_name = "bid_price" if direction == OrderDirection.BUY else "ask_price"
    else:
        quote_name = "ask_price" if direction == OrderDirection.BUY else "bid_price"
    quote = float(getattr(price_data, quote_name, 0.0) or 0.0)
    return quote if quote > 0 else float(getattr(price_data, "last_price", 0.0) or 0.0)


def _get_close_position_availability(
    position_detail: CTPPositionDetail,
    direction: str,
) -> Tuple[int, int, str]:
    """根据平仓方向返回可平昨仓、今仓和描述信息."""
    if direction == OrderDirection.BUY:
        return position_detail.short_yesterday, position_detail.short_today, "平空"

    return position_detail.long_yesterday, position_detail.long_today, "平多"


def _build_close_sequence(
    offset_priority: str,
    available_yesterday: int,
    available_today: int,
) -> Tuple[List[Tuple[str, int, str, str]], str]:
    """
    根据 ``offset_priority`` 构建分腿平仓顺序。

    Parameters
    ----------
    offset_priority : str
        平仓优先级，支持 ``昨今`` 和 ``今昨``。
    available_yesterday : int
        当前可平昨仓手数。
    available_today : int
        当前可平今仓手数。

    Returns
    -------
    Tuple[List[Tuple[str, int, str, str]], str]
        第一项为顺序化的平仓腿配置，第二项为便于日志审计的策略描述。
    """
    if offset_priority == "昨今":
        return [
            (THOST_FTDC_OF_CloseYesterday, available_yesterday, "平昨", "🔸"),
            (THOST_FTDC_OF_CloseToday, available_today, "平今", "🔹"),
        ], "先平昨再平今"

    return [
        (THOST_FTDC_OF_CloseToday, available_today, "平今", "🔸"),
        (THOST_FTDC_OF_CloseYesterday, available_yesterday, "平昨", "🔹"),
    ], "先平今再平昨"


def _submit_close_leg(
    executor: ExecutorProtocol,
    symbol: str,
    direction: str,
    close_volume: float,
    limit_price: float,
    offset_flag: str,
    start_message: str,
    success_message: str,
    failure_message: str,
    failure_level: str = "warning",
) -> Tuple[UnifiedOrder | None, float]:
    """提交单腿平仓订单，并按调用方要求记录日志."""
    try:
        executor.logger.info(start_message)
        order = executor.place_order(
            OrderDirection(direction),
            OrderType.LIMIT,
            close_volume,
            limit_price,
            **{"offset_flag": offset_flag},
        )
        executor.logger.info(success_message.format(order_id=order.order_id))
        return order, close_volume
    except Exception as e:
        getattr(executor.logger, failure_level)(failure_message.format(error=e))
        return None, 0


def _smart_close_position(
    executor: ExecutorProtocol,
    symbol: str,
    direction: str,
    close_volume: float,
    limit_price: float,
    offset_priority: str = "昨今",
) -> Tuple[List[UnifiedOrder], float, bool]:
    """
    按昨仓 / 今仓可用量智能拆分平仓顺序。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前执行器会话。
    symbol : str
        合约代码。
    direction : str
        买卖方向，支持 ``BUY`` 和 ``SELL``。
    close_volume : float
        计划平掉的手数。
    limit_price : float
        本次平仓使用的限价。
    offset_priority : str, default="昨今"
        平仓优先级，支持 ``昨今`` 和 ``今昨``。

    Returns
    -------
    Tuple[List[UnifiedOrder], float, bool]
        依次为订单列表、成功提交的平仓手数，以及是否完全满足目标。
    """
    orders: List[UnifiedOrder] = []

    if close_volume <= 0:
        return orders, 0, True

    executor.logger.info(f"🎯 开始智能平仓: {symbol} {direction} {close_volume}手, 优先级={offset_priority}")

    account_assets = executor.get_account_assets()
    position_detail = _extract_ctp_position_details(account_assets, [symbol]).get(symbol)

    if not position_detail:
        executor.logger.warning(f"⚠️ 无法获取{symbol}的持仓详情")
        return orders, 0, False

    available_yesterday, available_today, direction_desc = _get_close_position_availability(position_detail, direction)
    total_available = available_yesterday + available_today

    executor.logger.info(
        f"📊 {symbol} {direction_desc}持仓分析: "
        f"昨仓={available_yesterday}手, 今仓={available_today}手, 可平={total_available}手"
    )

    if total_available < close_volume:
        executor.logger.warning(f"⚠️ 可平仓手数不足: 需要{close_volume}手, 可平{total_available}手")
        close_volume = total_available

    if close_volume <= 0:
        return orders, 0, True

    executed_volume = 0
    remaining_volume = close_volume

    close_sequence, priority_desc = _build_close_sequence(offset_priority, available_yesterday, available_today)
    executor.logger.info(f"📋 平仓策略: {priority_desc}")

    for offset_flag, available_volume, offset_name, action_prefix in close_sequence:
        if remaining_volume <= 0 or available_volume <= 0:
            continue

        leg_volume = min(remaining_volume, available_volume)
        order, submitted_volume = _submit_close_leg(
            executor=executor,
            symbol=symbol,
            direction=direction,
            close_volume=leg_volume,
            limit_price=limit_price,
            offset_flag=offset_flag,
            start_message=f"{action_prefix} 执行{offset_name}: {leg_volume}手",
            success_message=f"✅ {offset_name}订单提交成功: {leg_volume}手, 订单ID: {{order_id}}",
            failure_message=f"❌ {offset_name}失败: {{error}}",
        )
        if not order:
            continue

        orders.append(order)
        executed_volume += submitted_volume
        remaining_volume -= submitted_volume

    # 只有在显式昨/今腿都无法覆盖目标时，才退回通用平仓标记，尽量保留更精确的
    # CTP offset_flag 语义。
    if remaining_volume > 0:
        fallback_volume = remaining_volume
        order, submitted_volume = _submit_close_leg(
            executor=executor,
            symbol=symbol,
            direction=direction,
            close_volume=fallback_volume,
            limit_price=limit_price,
            offset_flag=THOST_FTDC_OF_Close,
            start_message=f"🔄 最后尝试通用平仓: {fallback_volume}手",
            success_message="✅ 通用平仓订单提交成功: 订单ID: {order_id}",
            failure_message="❌ 通用平仓也失败: {error}",
            failure_level="error",
        )
        if order:
            orders.append(order)
            executed_volume += submitted_volume
            remaining_volume -= submitted_volume

    success = remaining_volume == 0
    if success:
        executor.logger.info(f"🎉 智能平仓完成: {symbol} 成功平仓 {executed_volume}手")
    else:
        executor.logger.warning(f"⚠️ 智能平仓部分成功: {symbol} 已平仓 {executed_volume}手, 剩余 {remaining_volume}手")

    return orders, executed_volume, success


def _execute_position_adjustment(
    executor: ExecutorProtocol,
    symbol: str,
    target_volume: float,
    position_detail: CTPPositionDetail,
    market_data: Any | None,
    price_type: str,
    offset_priority: str,
    *,
    trade_rule: Dict[str, Any] | None = None,
) -> List[UnifiedOrder]:
    """
    按目标净持仓执行单品种持仓调整。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前执行器会话。
    symbol : str
        品种代码。
    target_volume : float
        目标净持仓量。
    position_detail : CTPPositionDetail
        当前品种的 CTP 持仓详情。
    market_data : Any | None
        当前品种市场数据。
    price_type : str
        价格策略。
    offset_priority : str
        平仓优先级。
    trade_rule : Dict[str, Any] | None, optional
        当前品种的交易规则；其中 ``margin_ratio`` 在期权卖方场景下作为
        CTP 合约表保证金率为 0 时的兜底，会通过 ``executor.place_order``
        kwargs 透传到 trader 风控模块。

    Returns
    -------
    List[UnifiedOrder]
        生成的订单列表，可能同时包含平仓腿和开仓腿。
    """
    current_net = position_detail.net_position
    adjust_volume = target_volume - current_net
    orders: List[UnifiedOrder] = []

    if adjust_volume == 0:
        executor.logger.info(f"{symbol} 持仓已达目标，无需调整")
        return orders

    # 先根据净持仓调整方向选出报价侧，后续平仓腿和开仓腿共用这份价格策略。
    if adjust_volume > 0:
        limit_price = _calculate_order_price(market_data, price_type, "BUY")
    else:
        limit_price = _calculate_order_price(market_data, price_type, "SELL")

    executor.logger.info(
        f"{symbol}: 当前净持仓={current_net}, 目标={target_volume}, "
        f"调整={adjust_volume}, 价格={limit_price}, 策略={price_type}"
    )

    # CTP 调整遵循“先平反向仓，再开同向仓”的顺序，尽量避免净持仓先进一步偏离目标，
    # 同时让 offset_flag 与交易所持仓规则保持一致。
    if adjust_volume > 0:  # 需要增加净持仓
        if position_detail.short_total > 0:  # 先平空头
            close_volume = min(abs(adjust_volume), position_detail.short_total)
            close_orders, executed_volume, _ = _smart_close_position(
                executor, symbol, "BUY", close_volume, limit_price, offset_priority
            )
            orders.extend(close_orders)
            adjust_volume -= executed_volume

        if adjust_volume > 0:  # 开多头
            try:
                order = executor.place_order(
                    OrderDirection.BUY,
                    OrderType.LIMIT,
                    adjust_volume,
                    limit_price,
                    offset_flag=THOST_FTDC_OF_Open,
                    trade_rule=trade_rule,
                )
                orders.append(order)
                executor.logger.info(f"📈 开多仓: {symbol} {adjust_volume}手@{limit_price}, 订单ID: {order.order_id}")
            except Exception as e:
                executor.logger.error(f"❌ 开多仓失败: {symbol} {adjust_volume}手@{limit_price}, 错误: {e}")

    else:  # 需要减少净持仓
        adjust_volume = abs(adjust_volume)
        if position_detail.long_total > 0:  # 先平多头
            close_volume = min(adjust_volume, position_detail.long_total)
            close_orders, executed_volume, _ = _smart_close_position(
                executor, symbol, "SELL", close_volume, limit_price, offset_priority
            )
            orders.extend(close_orders)
            adjust_volume -= executed_volume

        if adjust_volume > 0:  # 开空头
            try:
                order = executor.place_order(
                    OrderDirection.SELL,
                    OrderType.LIMIT,
                    adjust_volume,
                    limit_price,
                    offset_flag=THOST_FTDC_OF_Open,
                    trade_rule=trade_rule,
                )
                orders.append(order)
                executor.logger.info(f"📉 开空仓: {symbol} {adjust_volume}手@{limit_price}, 订单ID: {order.order_id}")
            except Exception as e:
                executor.logger.error(f"❌ 开空仓失败: {symbol} {adjust_volume}手@{limit_price}, 错误: {e}")

    return orders


@register_algorithm(
    "TARGET-POS-TASK",
    channels=[TradeChannel.CTP, TradeChannel.TQ],
    params_class=CTPTargetPosTaskParams,
    label="期货目标持仓",
    description="按目标净持仓增减期货仓位，并处理今仓与昨仓的开平顺序。",
)
def ctp_target_pos_task_algorithm(executor: ExecutorProtocol, algorithm_input: AlgorithmInput) -> AlgorithmResult:
    """
    执行 CTP 目标持仓调整算法。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前执行器会话。
    algorithm_input : AlgorithmInput
        单品种算法输入；目标持仓量、交易规则与参数都已由上层规划完成。

    Returns
    -------
    AlgorithmResult
        本次单品种调仓的执行结果。

    Notes
    -----
    算法参数通过 ``algorithm_input.params`` 提供，主要包括 ``max_wait_seconds``、
    ``chase_enabled``、``chase_ticks``、``max_chase_count`` 和 ``chase_interval``。
    算法主线遵循“读取当前持仓 -> 先平反向仓 -> 再开同向仓 -> 回调驱动等待 ->
    最终再拉一次账户资产确认结果”。
    """
    algorithm_name = "TARGET-POS-TASK"

    executor.logger.info(f"🚀 开始{algorithm_name}算法执行")
    executor.logger.info(f"📋 算法输入: symbol={algorithm_input.symbol}, target_volume={algorithm_input.target_volume}")

    params = algorithm_input.params
    if not isinstance(params, CTPTargetPosTaskParams):
        raise TypeError(f"{algorithm_name} 参数应为 CTPTargetPosTaskParams，实际为 {type(params).__name__}")
    max_wait_seconds = params.max_wait_seconds
    chase_config = ChaseConfig.from_params(params)

    execution_memory: Dict[str, Any] = {}
    target_reached = False
    current_net_position = 0
    planned_symbol = algorithm_input.symbol
    market_data: Any | None = None

    account_assets = executor.get_account_assets()
    executor.logger.info(
        f"💰 账户总资产: {account_assets.total_asset:.2f}, 可用资金: {account_assets.available_cash:.2f}"
    )

    symbol = algorithm_input.symbol
    market_data = executor.get_market_data()
    if market_data:
        executor.logger.info(f"📊 获取到 {symbol} 的市场数据")

    # CTP 路径依赖回调驱动等待；先绑定 tracker 再开始下单，避免第一笔订单的
    # 订单/价格回调在注册前到达，导致后续等待态缺少状态来源。
    tracker = OrderTracker(executor=executor, chase_config=chase_config)
    executor.register_order_callback(tracker.on_order_update)
    if chase_config:
        executor.register_price_callback(tracker.on_price_update)
        if market_data is not None:
            tracker.latest_prices[symbol] = market_data

    try:
        position_details = _extract_ctp_position_details(account_assets, [symbol])
        symbol_position_detail = position_details.get(symbol)
        if symbol_position_detail:
            current_net_position = symbol_position_detail.net_position

        # 目标数量已经在通用执行层规划完成；CTP 算法这里不再重新解释组合权重，
        # 只负责把这一个 symbol 的目标落地成昨今仓友好的订单序列。
        target_volume = algorithm_input.target_volume
        first_tick = clone_price_data(market_data)

        executor.logger.info(f"🎯 目标持仓数量: {{'{symbol}': {target_volume}}}")

        trade_rule = algorithm_input.trade_rule
        price_type = str(trade_rule.get("price", params.price_strategy))
        offset_priority = str(trade_rule.get("offset_priority", params.offset_priority))

        executor.logger.info(f"📈 {symbol}: 目标={target_volume}, 价格策略={price_type}, 平仓优先级={offset_priority}")

        position_detail = position_details.get(symbol)
        if not position_detail:
            executor.logger.warning(f"⚠️ 无法获取{symbol}持仓详情，跳过")
        else:
            symbol_orders = _execute_position_adjustment(
                executor,
                symbol,
                target_volume,
                position_detail,
                market_data,
                price_type,
                offset_priority,
                trade_rule=trade_rule,
            )

            for order in symbol_orders:
                tracker.add_order(order)

            execution_memory[f"{symbol}_adjustment"] = {
                "current_net": position_detail.net_position,
                "target_volume": target_volume,
                "orders_generated": len(symbol_orders),
                "price_type": price_type,
                "offset_priority": offset_priority,
            }

        if tracker.get_pending_count() > 0:
            executor.logger.info(f"⏳ 等待 {tracker.get_pending_count()} 个订单完成...")
            tracker.wait_for_completion(timeout=max_wait_seconds)

        # 最终是否达标以重新拉取的账户资产为准，而不是依赖本地订单累计推断；
        # 这样可以覆盖交易所异步回报延迟、部分成交和通道侧补单等情况。
        final_account_assets = executor.get_account_assets()
        final_position_detail = _extract_ctp_position_details(final_account_assets, [symbol]).get(symbol)
        final_net_position = final_position_detail.net_position if final_position_detail else 0
        target_reached = final_net_position == target_volume
        target_gap = target_volume - final_net_position

        if not target_reached:
            executor.logger.warning(
                f"⚠️ {symbol} 最终持仓未达目标: 当前{final_net_position} 目标{target_volume} 差值{target_gap}"
            )

        result_status = ExecutionStatus.SUCCEEDED if target_reached else ExecutionStatus.FAILED
        executor.logger.info(f"✅ {algorithm_name}算法执行完成")

        orders = tracker.get_all_orders()
        trades = tracker.get_all_trades()

        return AlgorithmResult(
            orders=orders,
            trades=trades,
            account_assets=final_account_assets,
            target_volume=target_volume,
            first_tick=first_tick,
            memory={
                "algorithm": algorithm_name,
                "symbols_processed": 1,
                "orders_generated": len(orders),
                "trades_generated": len(trades),
                "symbol": planned_symbol,
                "target_volume": target_volume,
                "current_net_position": current_net_position,
                "final_net_position": final_net_position,
                "target_gap": target_gap if not target_reached else 0,
                "target_reached": target_reached,
                "execution_details": execution_memory,
                "total_asset_before": account_assets.total_asset,
                "total_asset_after": final_account_assets.total_asset,
                "chase_enabled": chase_config is not None,
            },
            status=result_status,
            error=None
            if target_reached
            else f"{symbol} 持仓调整失败: 当前净持仓 {final_net_position}，目标 {target_volume}",
        )

    except Exception as e:
        error_msg = f"{algorithm_name}算法执行失败: {e}"
        executor.logger.error(f"❌ {error_msg}")
        execution_memory["error"] = str(e)

        return AlgorithmResult(
            orders=tracker.get_all_orders(),
            trades=tracker.get_all_trades(),
            account_assets=executor.get_account_assets(),
            target_volume=algorithm_input.target_volume,
            first_tick=clone_price_data(market_data),
            status=ExecutionStatus.FAILED,
            error=error_msg,
            memory={
                "algorithm": algorithm_name,
                "success": False,
                "error": error_msg,
                "execution_details": execution_memory,
            },
        )

    finally:
        # 回调注册属于一次执行的临时资源；无论成功失败都必须释放，避免污染后续
        # symbol 执行或让旧 tracker 继续消费新订单事件。
        executor.unregister_order_callback(tracker.on_order_update)
        if chase_config:
            executor.unregister_price_callback(tracker.on_price_update)

"""订单操作辅助函数.

提供算法中通用的订单操作工具函数，减少代码重复。
"""

from dataclasses import dataclass

from axile.domain.execution import ExecutionEventStatus, ExecutionEventType, ExecutionReasonFamily
from axile.executor.algorithms.core.base import ExecutorProtocol
from axile.executor.algorithms.exceptions import SubMinQuantityError
from axile.executor.algorithms.utils.order_tracker import ChaseConfig, OrderTracker
from axile.executor.models.unified_account_assets import PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


def determine_position_side(
    executor: ExecutorProtocol,
    direction: OrderDirection,
    account_assets: UnifiedAccountAssets,
) -> dict[str, str]:
    """
    为双向持仓模式推导 ``position_side`` 参数。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    direction : OrderDirection
        当前订单方向。
    account_assets : UnifiedAccountAssets
        当前账户资产快照。

    Returns
    -------
    dict[str, str]
        包含 ``position_side`` 的下单附加参数；当前订单不涉及平已有仓位时返回空字典。

    Notes
    -----
    该函数只在双向持仓语义下有意义。算法层不直接
    关心账户模式细节，而是根据当前持仓方向推导应平掉哪一边仓位。
    """
    position_side_kwargs: dict[str, str] = {}
    symbol = executor.symbol

    try:
        positions = executor.get_positions(account_assets)
    except Exception as e:
        executor.logger.warning(f"获取 {symbol} 持仓失败: {e}")
        return position_side_kwargs

    if direction == OrderDirection.SELL:
        for pos_vol, pos_dir in positions:
            if pos_dir == PositionDirection.LONG and pos_vol > 0:
                position_side_kwargs["position_side"] = "LONG"
                executor.logger.debug(f"{symbol} 卖出将平多头持仓")
                break
    elif direction == OrderDirection.BUY:
        for pos_vol, pos_dir in positions:
            if pos_dir == PositionDirection.SHORT and pos_vol > 0:
                position_side_kwargs["position_side"] = "SHORT"
                executor.logger.debug(f"{symbol} 买入将平空头持仓")
                break

    return position_side_kwargs


@dataclass(frozen=True)
class OrderDecision:
    """
    单向持仓下单前的可行性裁决结果.

    Attributes
    ----------
    action : str
        ``"SEND"`` 表示照常提交；``"SKIP"`` 表示本单不可行、应跳过不下。
    reduce_only : bool
        是否以 reduceOnly 方式下单。纯减仓且名义价值不足最小值时置真，
        借交易所对减仓单的豁免突破最小名义价值限制。
    reason : str
        裁决原因码，用于审计事件与诊断日志。
    """

    action: str
    reduce_only: bool = False
    reason: str = ""


def _reference_price(executor: ExecutorProtocol, price: float) -> float:
    """
    解析用于估算名义价值的参考价.

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    price : float
        下单价格；市价单通常为 ``0``。

    Returns
    -------
    float
        参考价。限价单直接返回 ``price``；市价单回退到行情快照的最新价，
        再退到买一卖一中值；均不可得时返回 ``0.0``。
    """
    if price > 0:
        return price
    market = executor.get_market_data()
    if market is None:
        return 0.0
    if market.last_price > 0:
        return market.last_price
    if market.bid_price > 0 and market.ask_price > 0:
        return (market.bid_price + market.ask_price) / 2
    return 0.0


def resolve_reduce_intent(
    executor: ExecutorProtocol,
    direction: OrderDirection,
    volume: float,
    target_volume: float,
    current_volume: float,
    price: float,
) -> OrderDecision:
    """
    在单向持仓语义下裁决订单可行性并推导 reduceOnly.

    连续目标经 ``目标 - 现仓`` 得到的下单量，未必落在交易所可执行的格点上：
    交易所对每笔增加敞口的订单设有最小名义价值下界，减仓单则可借 reduceOnly
    豁免。本函数据此把订单归入三类之一：名义达标照常发、纯减仓借 reduceOnly
    突破、加仓或翻向余量过小则跳过。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话，用于读取最小名义价值与行情。
    direction : OrderDirection
        下单方向。
    volume : float
        本单下单数量（恒为正）。
    target_volume : float
        本轮规划的目标净持仓。
    current_volume : float
        下单前的当前净持仓（多为正、空为负）。
    price : float
        下单价格；市价单传 ``0`` 时回退到行情快照估算名义价值。

    Returns
    -------
    OrderDecision
        裁决结果。渠道无最小名义价值信息或参考价缺失时退化为 ``"SEND"``，
        保持既有行为不变。

    Notes
    -----
    穿零翻向单（``volume > |current_volume|``）同时含平仓与反向开仓两段，
    整单套 reduceOnly 会被交易所封顶在平到零、反向开仓段静默不成交，
    因此此类订单绝不置 ``reduce_only``。
    """
    min_notional = executor.get_min_notional()
    if not isinstance(min_notional, int | float) or min_notional <= 0:
        return OrderDecision(action="SEND")

    ref_price = _reference_price(executor, price)
    if ref_price <= 0:
        return OrderDecision(action="SEND")

    if volume * ref_price >= min_notional:
        return OrderDecision(action="SEND")

    # 名义价值不足最小值：仅"纯减仓"可借 reduceOnly 突破。
    is_reduce_direction = current_volume != 0 and (
        (direction == OrderDirection.SELL and current_volume > 0)
        or (direction == OrderDirection.BUY and current_volume < 0)
    )
    crosses_zero = volume > abs(current_volume)

    if is_reduce_direction and not crosses_zero:
        return OrderDecision(action="SEND", reduce_only=True, reason="pure_reduce_below_min_notional")

    _ = target_volume  # 目标仅用于语义完整；清仓（目标为 0）已落入纯减仓分支。
    return OrderDecision(action="SKIP", reason="increase_below_min_notional")


def setup_order_tracker(
    executor: ExecutorProtocol,
    market_data: UnifiedPriceData | None,
    chase_config: ChaseConfig | None,
) -> OrderTracker:
    """
    创建订单跟踪器并完成回调绑定。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    market_data : UnifiedPriceData | None
        当前品种的行情快照；启用追单时会作为初始盘口。
    chase_config : ChaseConfig | None
        追单配置；为空时仅启用订单/成交跟踪。

    Returns
    -------
    OrderTracker
        已完成标准回调注册的订单跟踪器。

    Notes
    -----
    这里把回调注册集中到单个入口，是为了让算法实现只关注“下单和等待”，而不必
    在每个算法里重复处理回调绑定与追单初始化细节。
    """
    tracker = OrderTracker(
        executor=executor,
        chase_config=chase_config,
        order_refresh_interval=30.0,
    )

    executor.register_order_callback(tracker.on_order_update)
    register_trade_callback = getattr(executor, "register_trade_callback", None)
    if callable(register_trade_callback):
        register_trade_callback(tracker.on_trade_record)

    # 追单逻辑依赖最新盘口；若算法启动时已经拿到一份快照，这里先放入 tracker，
    # 避免在第一笔订单尚未收到价格回调前就失去追单判断依据。
    if chase_config:
        executor.register_price_callback(tracker.on_price_update)
        if market_data is not None:
            tracker.latest_prices[executor.symbol] = market_data

    executor.logger.debug(f"订单跟踪器已设置: symbol={executor.symbol}, chase={chase_config is not None}")

    return tracker


def teardown_order_tracker(
    executor: ExecutorProtocol,
    tracker: OrderTracker,
    chase_config: ChaseConfig | None,
) -> None:
    """
    注销订单跟踪器相关回调并做尾部清理。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    tracker : OrderTracker
        本次算法使用的订单跟踪器。
    chase_config : ChaseConfig | None
        追单配置；为空时跳过价格回调清理。

    Notes
    -----
    清理阶段保持 best-effort。回调注销失败不应覆盖算法主流程的真实执行结果，
    因此这里只记录告警。
    """
    try:
        executor.unregister_order_callback(tracker.on_order_update)
    except Exception as e:
        executor.logger.warning(f"注销订单回调失败: {e}")

    unregister_trade_callback = getattr(executor, "unregister_trade_callback", None)
    if callable(unregister_trade_callback):
        try:
            unregister_trade_callback(tracker.on_trade_record)
        except Exception as e:
            executor.logger.warning(f"注销成交回调失败: {e}")

    if chase_config:
        try:
            executor.unregister_price_callback(tracker.on_price_update)
        except Exception as e:
            executor.logger.warning(f"注销价格回调失败: {e}")

    executor.logger.debug("订单跟踪器已清理")


def submit_and_track_order(
    executor: ExecutorProtocol,
    tracker: OrderTracker,
    direction: OrderDirection,
    order_type: OrderType,
    volume: float,
    price: float,
    target_volume: float,
    current_volume: float,
    **kwargs: object,
) -> UnifiedOrder | None:
    """
    提交订单并纳入统一跟踪流程。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    tracker : OrderTracker
        负责收敛订单与成交状态的跟踪器。
    direction : OrderDirection
        下单方向。
    order_type : OrderType
        订单类型。
    volume : float
        下单数量。
    price : float
        下单价格；市价单通常传 ``0``。
    target_volume : float
        本轮执行规划出的目标持仓量。
    current_volume : float
        提交订单前的当前持仓量。
    **kwargs : object
        额外的下单参数，例如 ``position_side``。

    Returns
    -------
    UnifiedOrder | None
        执行器返回的订单对象；当本单因名义价值不足最小值且不可借 reduceOnly
        突破而被跳过时返回 ``None``。

    Notes
    -----
    先下单再写入 tracker，是因为订单主键只能由执行器返回；tracker 里的追单与
    剩余量计算都依赖这份真实订单对象。

    下单前先经 :func:`resolve_reduce_intent` 做单向持仓可行性裁决：纯减仓且
    名义价值不足时注入 ``reduce_only``；加仓或翻向余量过小则记审计事件后跳过。
    """
    symbol = executor.symbol

    decision = resolve_reduce_intent(executor, direction, volume, target_volume, current_volume, price)
    if decision.action == "SKIP":
        executor.emit_audit_event(
            event_type=ExecutionEventType.SYMBOL_SKIPPED,
            status=ExecutionEventStatus.WARNING,
            reason_family=ExecutionReasonFamily.MARKET_RULE,
            reason_code="COMMON.SUB_MIN_NOTIONAL",
            symbol=symbol,
            details={
                "direction": direction.value,
                "order_type": order_type.value,
                "volume": float(volume),
                "price": float(price),
                "target_volume": float(target_volume),
                "current_volume": float(current_volume),
                "reason": decision.reason,
            },
        )
        executor.logger.info(f"{symbol} {direction.value} {volume} 名义价值不足最小值，跳过下单（{decision.reason}）")
        return None
    if decision.reduce_only:
        kwargs["reduce_only"] = True

    try:
        order = executor.place_order(
            direction,
            order_type,
            volume,
            price,
            **kwargs,
        )
    except SubMinQuantityError as exc:
        # 碎量按步长取整后归零：视作「该品种无可执行动作」而非下单失败，记跳过事件并放行。
        executor.emit_audit_event(
            event_type=ExecutionEventType.SYMBOL_SKIPPED,
            status=ExecutionEventStatus.WARNING,
            reason_family=ExecutionReasonFamily.MARKET_RULE,
            reason_code="COMMON.SUB_MIN_QTY",
            symbol=symbol,
            details={
                "direction": direction.value,
                "order_type": order_type.value,
                "volume": float(volume),
                "price": float(price),
                "target_volume": float(target_volume),
                "current_volume": float(current_volume),
                "reason": str(exc),
            },
        )
        executor.logger.info(f"{symbol} {direction.value} {volume} 取整后数量为 0，跳过下单")
        return None

    # 补发「挂单」审计事件，供前端逐只动作流呈现「决策→挂单→追价→成交」中的挂单一步。
    # 无审计上下文时 emit_audit_event 自身静默跳过，故对无上下文的渠道零影响。
    client_order_id = order.extra.get("cl_ord_id") if isinstance(order.extra, dict) else None
    executor.emit_audit_event(
        event_type=ExecutionEventType.ORDER_SUBMITTED,
        status=ExecutionEventStatus.INFO,
        reason_family=ExecutionReasonFamily.EXECUTION_STRATEGY,
        reason_code="COMMON.ORDER_SUBMITTED",
        symbol=symbol,
        order_id=order.order_id,
        client_order_id=client_order_id if isinstance(client_order_id, str) else None,
        details={
            "order": {
                "direction": direction.value,
                "order_type": order_type.value,
                "volume": float(volume),
                "price": float(price),
            }
        },
    )

    position_side = kwargs.get("position_side")
    tracker.add_order(
        order,
        direction=direction,
        target_volume=float(target_volume),
        current_volume=float(current_volume),
        position_side=position_side if isinstance(position_side, str) else None,
    )

    executor.logger.debug(f"订单已提交: {symbol} {direction.value} {volume} @{price}, 订单ID: {order.order_id}")

    return order

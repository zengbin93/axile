"""
POV（Percentage of Volume，参与率）算法.

按「市场实时成交量」的固定比例跟单：市场成交活跃时多下、清淡时少下，
使自身始终只占市场成交的一小部分，从而降低冲击成本、隐蔽大单。

设计要点
--------
- 目标语义为「净持仓」：先把 ``target_volume`` 转成相对当前持仓的增量，再对增量按
  市场量参与，因此表达「调仓到位」而非「买入 N 手」。
- 市场成交量来源：注册价格回调，累加每次行情更新携带的**增量成交量**
  （``UnifiedPriceData.volume``）。仿真逐 tick 增量；累计型渠道（如 CTP 日内累计量）
  需另行适配，暂不在本实现范围。
- 累计跟踪：目标累计成交 = ``参与率 × 已见市场量``，本轮下单量 = 该目标减去已成交量，
  与 TWAP 的累计进度表同思想——天然实现对欠量的追平，且不超过整体目标。
- 无量安全：市场无量则不下单，跑到 ``max_duration`` 上限；``complete_on_timeout`` 为真时
  到期补齐剩余量，兑现框架「调仓到位」契约。
- 全渠道通用：不在算法层做 lot / 最小下单量取整，交由各渠道执行器兜底。

使用示例
--------
    input_data = UnifiedStandardInput(
        algorithm={
            "method": "POV",
            "params": {
                "participation_rate": 0.1,
                "interval_seconds": 5,
                "max_duration": 600,
                "price_strategy": "ACTIVE",
                "complete_on_timeout": True,
            },
        },
        ...
    )
"""

from typing import Any, Literal

from pydantic import Field, model_validator

from axile.executor.algorithms.common.params import BaseAlgorithmParams
from axile.executor.algorithms.core.base import (
    AlgorithmInput,
    AlgorithmResult,
    ExecutorProtocol,
    OrderDirection,
    register_algorithm,
)
from axile.executor.algorithms.exceptions import RECOVERABLE_ALGORITHM_EXCEPTIONS, format_exception_message
from axile.executor.algorithms.utils import (
    determine_order_price,
    determine_position_side,
    get_default_clock,
    setup_order_tracker,
    submit_and_track_order,
    teardown_order_tracker,
)
from axile.executor.algorithms.utils.order_tracker import OrderTracker
from axile.executor.algorithms.utils.trading import cancel_pending_orders_via_query, create_empty_result
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_price import UnifiedPriceData, clone_price_data

ALGORITHM_NAME = "POV"


class PovParams(BaseAlgorithmParams):
    """
    POV 算法参数.

    Attributes
    ----------
    participation_rate : float
        目标市场成交量参与比例，范围 (0, 1]。
    interval_seconds : float
        轮询与下单节奏（秒），不小于 0.1。
    max_duration : int
        硬时间上限（秒），范围 1-86400，且不小于 ``interval_seconds``。
    price_strategy : {"ACTIVE", "PASSIVE"}
        单片下单价格策略。``ACTIVE`` 取对手价（marketable，跟量成交更确定），
        ``PASSIVE`` 取本方价（滑点更小但可能欠量）。
    complete_on_timeout : bool
        到达时间上限且仍有欠量时，是否补齐剩余量到目标。
    """

    participation_rate: float = Field(
        default=0.1,
        gt=0.0,
        le=1.0,
        description="目标市场成交量参与比例，范围：(0, 1]",
    )
    interval_seconds: float = Field(
        default=5.0,
        ge=0.1,
        description="轮询/下单节奏（秒），不小于 0.1",
    )
    max_duration: int = Field(
        default=600,
        ge=1,
        le=86400,
        description="硬时间上限（秒），范围：1-86400",
    )
    price_strategy: Literal["ACTIVE", "PASSIVE"] = "ACTIVE"
    complete_on_timeout: bool = True

    @model_validator(mode="after")
    def _validate_duration(self) -> "PovParams":
        """
        校验时间上限至少容纳一个轮询间隔.

        Returns
        -------
        PovParams
            通过校验的参数对象。

        Raises
        ------
        ValueError
            ``max_duration`` 小于 ``interval_seconds`` 时抛出。
        """
        if self.max_duration < self.interval_seconds:
            raise ValueError(
                f"max_duration（{self.max_duration}秒）不应小于 interval_seconds"
                f"（{self.interval_seconds}秒），否则无法完成一个轮询。"
            )
        return self

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        return (
            "PovParams("
            f"participation_rate={self.participation_rate}, "
            f"interval_seconds={self.interval_seconds}, "
            f"max_duration={self.max_duration}, "
            f"price_strategy={self.price_strategy}, "
            f"complete_on_timeout={self.complete_on_timeout})"
        )


class _VolumeAccumulator:
    """累加价格回调携带的增量市场成交量.

    Notes
    -----
    仿真下回调与算法同线程、同步触发；真实渠道下由 WebSocket 线程写、算法线程读。
    仅有单一写入方且累加单调，读取允许轻微滞后，故不加锁。
    """

    def __init__(self) -> None:
        """初始化累加器."""
        self.total: float = 0.0

    def on_price(self, price_data: UnifiedPriceData) -> None:
        """价格回调：累加非负增量成交量.

        Parameters
        ----------
        price_data : UnifiedPriceData
            一次行情更新快照。
        """
        volume = price_data.volume
        if volume and volume > 0:
            self.total += volume


def compute_participation_want(
    participation_rate: float,
    market_seen: float,
    filled: float,
    total_qty: float,
) -> float:
    """
    按累计参与率推导本轮应补下的数量.

    Parameters
    ----------
    participation_rate : float
        目标市场成交量参与比例。
    market_seen : float
        截至当前累计观测到的市场成交量。
    filled : float
        截至当前的累计已成交量。
    total_qty : float
        本次执行需要成交的总量（增量绝对值）。

    Returns
    -------
    float
        本轮应下的数量；不足以下单时返回 ``0.0``。

    Notes
    -----
    目标累计成交 = ``参与率 × 已见市场量``；本轮补下量为该目标减去已成交量，
    并以「距目标的剩余量」封顶，确保追平欠量但不超过整体目标。
    """
    desired_cum = participation_rate * market_seen
    want = min(desired_cum - filled, total_qty - filled)
    return max(want, 0.0)


def _place_participation_slice(
    executor: ExecutorProtocol,
    tracker: OrderTracker,
    direction: OrderDirection,
    slice_qty: float,
    params: PovParams,
    account_assets: UnifiedAccountAssets,
    current_volume: float,
    target_volume: float,
    fill_wait_seconds: float,
) -> dict[str, Any]:
    """
    执行单个参与切片：下单、等待成交、撤除未成交余量.

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    tracker : OrderTracker
        跨切片复用的订单跟踪器。
    direction : OrderDirection
        下单方向。
    slice_qty : float
        本片下单量。
    params : PovParams
        POV 参数。
    account_assets : UnifiedAccountAssets
        本片开始时的账户资产快照。
    current_volume : float
        本片开始时的当前持仓量。
    target_volume : float
        整体目标持仓量。
    fill_wait_seconds : float
        本片等待成交的最长时间（秒）。

    Returns
    -------
    dict[str, Any]
        本片执行明细；下单失败时包含 ``error`` 字段。

    Notes
    -----
    片末主动撤除未成交余量，避免其在后续轮询间隔成交而破坏累计量核对；
    未成交余量由后续轮次的累计参与自动补回。
    """
    order_type, price = determine_order_price(
        direction,
        executor.get_market_data(),
        price_strategy=params.price_strategy,
    )
    position_side_kwargs = determine_position_side(executor, direction, account_assets)

    detail: dict[str, Any] = {
        "direction": direction.value,
        "volume": slice_qty,
        "order_type": order_type.value,
        "price": price,
    }

    try:
        order = submit_and_track_order(
            executor,
            tracker,
            direction,
            order_type,
            slice_qty,
            price,
            target_volume=float(target_volume),
            current_volume=float(current_volume),
            **position_side_kwargs,
        )
        if order is None:
            detail["skipped"] = "sub_min_notional"
            return detail
        detail["order_id"] = order.order_id
    except MemoryError:
        executor.logger.exception(f"[{ALGORITHM_NAME}] {executor.symbol} 下单遇到不可恢复异常")
        raise
    except RECOVERABLE_ALGORITHM_EXCEPTIONS as exc:
        error_message = format_exception_message(exc)
        executor.logger.error(f"[{ALGORITHM_NAME}] {executor.symbol} 下单失败: {error_message}")
        detail["error"] = error_message
        return detail

    tracker.wait_for_completion(timeout=fill_wait_seconds)
    cancel_pending_orders_via_query(executor)
    return detail


@register_algorithm(
    ALGORITHM_NAME,
    params_class=PovParams,
    label="成交量参与率",
    description="按市场实时成交量的固定比例逐步下单，控制自身成交占比。",
)
def pov(
    executor: ExecutorProtocol,
    algorithm_input: AlgorithmInput,
) -> AlgorithmResult:
    """
    POV（参与率）算法.

    按市场实时成交量的固定比例，把目标净持仓相对当前持仓的增量逐步做到位。

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    algorithm_input : AlgorithmInput
        单品种执行输入，``params`` 应为 :class:`PovParams`。

    Returns
    -------
    AlgorithmResult
        本次执行的订单、成交与账户快照汇总。

    Raises
    ------
    TypeError
        当 ``algorithm_input.params`` 不是 :class:`PovParams` 时抛出。
    """
    params = algorithm_input.params
    if not isinstance(params, PovParams):
        raise TypeError(f"POV 参数应为 PovParams，实际为 {type(params).__name__}")

    symbol = algorithm_input.symbol
    target_volume = algorithm_input.target_volume

    account_assets = executor.get_account_assets()
    start_volume = executor.get_current_volume(account_assets)
    first_tick = clone_price_data(executor.get_market_data())

    delta = target_volume - start_volume
    if delta == 0:
        executor.logger.info(f"[{ALGORITHM_NAME}] {symbol} 当前持仓已等于目标 {target_volume}，无需执行")
        return create_empty_result(account_assets, ALGORITHM_NAME, "当前持仓已等于目标，无需执行")

    direction = OrderDirection.BUY if delta > 0 else OrderDirection.SELL
    total_qty = abs(delta)
    interval = params.interval_seconds
    fill_wait = min(interval, float(params.max_wait_seconds))

    executor.logger.info(
        f"[{ALGORITHM_NAME}] {symbol} 开始执行: 目标={target_volume}, 当前={start_volume}, 增量={delta}, {params}"
    )

    accumulator = _VolumeAccumulator()
    tracker = setup_order_tracker(executor, executor.get_market_data(), None)
    executor.register_price_callback(accumulator.on_price)
    slice_details: list[dict[str, Any]] = []

    try:
        _run_participation_loop(
            executor,
            tracker,
            accumulator,
            params,
            direction,
            total_qty,
            start_volume,
            target_volume,
            fill_wait,
            slice_details,
        )
    finally:
        executor.unregister_price_callback(accumulator.on_price)
        teardown_order_tracker(executor, tracker, None)

    account_assets = executor.get_account_assets()
    final_volume = executor.get_current_volume(account_assets)
    orders = tracker.get_all_orders()
    trades = tracker.get_all_trades()

    executor.logger.info(
        f"[{ALGORITHM_NAME}] {symbol} 执行完成: 最终持仓={final_volume}, 目标={target_volume}, "
        f"市场累计量={accumulator.total:.4f}, 订单数={len(orders)}, 成交数={len(trades)}"
    )

    return AlgorithmResult(
        orders=orders,
        trades=trades,
        account_assets=account_assets,
        target_volume=target_volume,
        first_tick=first_tick,
        memory={
            "algorithm": ALGORITHM_NAME,
            "target_volume": target_volume,
            "start_volume": start_volume,
            "final_volume": final_volume,
            "total_quantity": total_qty,
            "participation_rate": params.participation_rate,
            "market_volume_seen": accumulator.total,
            "slice_details": slice_details,
            "orders_generated": len(orders),
            "trades_generated": len(trades),
            "total_asset": account_assets.total_asset,
        },
    )


def _run_participation_loop(
    executor: ExecutorProtocol,
    tracker: OrderTracker,
    accumulator: _VolumeAccumulator,
    params: PovParams,
    direction: OrderDirection,
    total_qty: float,
    start_volume: float,
    target_volume: float,
    fill_wait: float,
    slice_details: list[dict[str, Any]],
) -> None:
    """
    运行 POV 参与主循环，就地追加逐片执行明细.

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    tracker : OrderTracker
        跨切片复用的订单跟踪器。
    accumulator : _VolumeAccumulator
        市场成交量累加器。
    params : PovParams
        POV 参数。
    direction : OrderDirection
        下单方向。
    total_qty : float
        需要成交的总量（增量绝对值）。
    start_volume : float
        执行开始时的当前持仓量。
    target_volume : float
        整体目标持仓量。
    fill_wait : float
        单片等待成交的最长时间（秒）。
    slice_details : list[dict[str, Any]]
        执行明细列表，就地追加逐片与补单明细。

    Notes
    -----
    循环按 ``interval`` 节奏轮询：读取已成交量与已见市场量，按累计参与率补下；
    达到目标即提前退出；到达时间上限后，``complete_on_timeout`` 为真则补齐剩余量。
    """
    clock = get_default_clock()
    interval = params.interval_seconds
    deadline = clock.time() + params.max_duration

    while clock.time() < deadline:
        executor.handle_termination_checkpoint()

        account_assets = executor.get_account_assets()
        current_volume = executor.get_current_volume(account_assets)
        filled = abs(current_volume - start_volume)
        if filled >= total_qty:
            break

        want = compute_participation_want(params.participation_rate, accumulator.total, filled, total_qty)
        if want > 0:
            executor.logger.info(
                f"[{ALGORITHM_NAME}] {executor.symbol} 参与下单 {want}"
                f"（已见市场量 {accumulator.total:.4f}, 已成交 {filled}/{total_qty}）"
            )
            detail = _place_participation_slice(
                executor, tracker, direction, want, params, account_assets, current_volume, target_volume, fill_wait
            )
            detail["market_seen"] = accumulator.total
            slice_details.append(detail)

        executor.sleep_or_terminate(interval)

    _maybe_complete_on_timeout(
        executor, tracker, params, direction, total_qty, start_volume, target_volume, fill_wait, slice_details
    )


def _maybe_complete_on_timeout(
    executor: ExecutorProtocol,
    tracker: OrderTracker,
    params: PovParams,
    direction: OrderDirection,
    total_qty: float,
    start_volume: float,
    target_volume: float,
    fill_wait: float,
    slice_details: list[dict[str, Any]],
) -> None:
    """
    到达时间上限后按需补齐剩余量到目标.

    Parameters
    ----------
    executor : ExecutorProtocol
        当前算法绑定的执行器会话。
    tracker : OrderTracker
        跨切片复用的订单跟踪器。
    params : PovParams
        POV 参数。
    direction : OrderDirection
        下单方向。
    total_qty : float
        需要成交的总量（增量绝对值）。
    start_volume : float
        执行开始时的当前持仓量。
    target_volume : float
        整体目标持仓量。
    fill_wait : float
        补单等待成交的最长时间（秒）。
    slice_details : list[dict[str, Any]]
        执行明细列表，就地追加补单明细。
    """
    if not params.complete_on_timeout:
        return

    account_assets = executor.get_account_assets()
    current_volume = executor.get_current_volume(account_assets)
    filled = abs(current_volume - start_volume)
    remaining = total_qty - filled
    if remaining <= 0:
        return

    executor.logger.info(
        f"[{ALGORITHM_NAME}] {executor.symbol} 到期补齐剩余量 {remaining}（已成交 {filled}/{total_qty}）"
    )
    detail = _place_participation_slice(
        executor, tracker, direction, remaining, params, account_assets, current_volume, target_volume, fill_wait
    )
    detail["reason"] = "complete_on_timeout"
    slice_details.append(detail)

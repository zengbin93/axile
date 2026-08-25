"""
单一做市商算法（回调版本）.

使用事件驱动等待，支持追单功能。
适用于提供统一订单与行情能力的执行器。

使用示例：
    input_data = UnifiedStandardInput(
        algorithm={
            "method": "SINGLE-MAKER",
            "params": {
                "max_wait_seconds": 60,
                "chase_enabled": True,
                "chase_ticks": 1,
                "max_chase_count": 5,
                "chase_interval": 5,
            }
        },
        ...
    )
"""

from typing import Any, Literal

from axile.executor.algorithms.common.params import BaseAlgorithmParams, ChaseParamsMixin
from axile.executor.algorithms.core.base import (
    AlgorithmInput,
    AlgorithmResult,
    ExecutorProtocol,
    OrderDirection,
    OrderType,
    register_algorithm,
)
from axile.executor.algorithms.exceptions import RECOVERABLE_ALGORITHM_EXCEPTIONS, format_exception_message
from axile.executor.algorithms.utils import (
    determine_order_price,
    determine_position_side,
    setup_order_tracker,
    submit_and_track_order,
    teardown_order_tracker,
)
from axile.executor.algorithms.utils.order_tracker import ChaseConfig
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_price import UnifiedPriceData, clone_price_data


class SingleMakerParams(BaseAlgorithmParams, ChaseParamsMixin):
    """SINGLE-MAKER 算法参数."""

    price_strategy: Literal["PASSIVE", "ACTIVE"] = "ACTIVE"
    on_missing_book: Literal["skip", "active", "market"] = "skip"

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        return (
            "SingleMakerParams("
            f"max_wait_seconds={self.max_wait_seconds}, "
            f"chase_enabled={self.chase_enabled}, "
            f"price_strategy={self.price_strategy}, "
            f"on_missing_book={self.on_missing_book})"
        )


def _resolve_pricing_on_book(
    direction: OrderDirection,
    market_data: UnifiedPriceData | None,
    params: SingleMakerParams,
) -> tuple[OrderType, float] | None:
    """
    结合盘口有效性与 ``on_missing_book`` 策略推导挂价.

    Parameters
    ----------
    direction : OrderDirection
        订单方向。
    market_data : UnifiedPriceData | None
        当前品种盘口快照。
    params : SingleMakerParams
        算法参数。

    Returns
    -------
    tuple[OrderType, float] | None
        ``(order_type, price)``；当盘口买卖一无效且 ``on_missing_book="skip"`` 时返回
        ``None``，表示本轮跳过该品种（欠量、下轮重挂），绝不穿价成 taker。
    """
    book_ok = market_data is not None and market_data.book_valid
    if book_ok:
        return determine_order_price(direction, market_data, price_strategy=params.price_strategy)
    # 盘口无效（未命中 bookTicker 被 last_price 兜底的假盘口）：按 on_missing_book 决策
    if params.on_missing_book == "skip":
        return None
    if params.on_missing_book == "market":
        return OrderType.MARKET, 0.0
    # active：退化成对手价（可成交，接受 taker）
    return determine_order_price(direction, market_data, price_strategy="ACTIVE")


@register_algorithm(
    "SINGLE-MAKER",
    params_class=SingleMakerParams,
    label="单边挂单",
    description="在盘口本方或对手价挂单等待成交，并可按配置追单。",
)
def single_maker_callback(
    executor: ExecutorProtocol,
    algorithm_input: AlgorithmInput,
) -> AlgorithmResult:
    """单一做市商算法（回调版本）.

    使用事件驱动等待，支持追单功能。
    适用于提供统一订单与行情能力的执行器。

    算法参数（通过 algorithm_input.params 配置）：
        - max_wait_seconds: 最大等待时间（秒），默认 60
        - chase_enabled: 是否启用追单，默认 False
        - chase_ticks: 价格偏离多少跳后追单，默认 1
        - max_chase_count: 单个订单最大追单次数，默认 5
        - chase_interval: 追单间隔（秒），默认 5
        - price_strategy: 下单价格策略，默认 ACTIVE
    """
    algorithm_name = "SINGLE-MAKER"

    params = algorithm_input.params
    if not isinstance(params, SingleMakerParams):
        raise TypeError(f"SINGLE-MAKER 参数应为 SingleMakerParams，实际为 {type(params).__name__}")
    max_wait_seconds = params.max_wait_seconds
    chase_config = ChaseConfig.from_params(params)

    executor.logger.info(f"追单配置: {chase_config is not None}")

    account_assets = executor.get_account_assets()
    log_debug = getattr(executor.logger, "debug", executor.logger.info)
    log_debug(f"账户总资产: {account_assets.total_asset:.2f}")

    symbol = algorithm_input.symbol
    market_data = executor.get_market_data()
    if market_data:
        log_debug(f"获取到 {symbol} 的价格数据")

    target_volume = algorithm_input.target_volume
    first_tick = clone_price_data(market_data)

    # 使用工具函数设置订单跟踪器
    tracker = setup_order_tracker(executor, market_data, chase_config)

    execution_memory: dict[str, Any] = {}

    try:
        executor.logger.info(f"开始执行 {symbol} 的交易")

        # 执行调仓
        current_volume = executor.get_current_volume(account_assets)

        if target_volume != current_volume:
            direction = OrderDirection.BUY if target_volume > current_volume else OrderDirection.SELL
            needed_volume = abs(target_volume - current_volume)
            pricing = _resolve_pricing_on_book(direction, market_data, params)
            if pricing is None:
                # 盘口无效 + on_missing_book=skip：本轮跳过该品种（欠量，下轮 rebalance 重挂），永不 taker
                executor.logger.warning(f"{symbol} 盘口买卖一无效（假盘口），本轮跳过（skip）")
                execution_memory[f"{symbol}_skipped"] = "missing_book"
                return AlgorithmResult(
                    orders=[],
                    trades=[],
                    account_assets=account_assets,
                    target_volume=target_volume,
                    first_tick=first_tick,
                    status=ExecutionStatus.NOOP,
                    memory={
                        "algorithm": algorithm_name,
                        "target_volume": algorithm_input.target_volume,
                        "execution_details": execution_memory,
                        "symbols_processed": 1,
                        "orders_generated": 0,
                        "trades_generated": 0,
                        "total_asset": account_assets.total_asset,
                        "chase_enabled": chase_config is not None,
                    },
                )
            order_type, price = pricing

            # 使用工具函数确定 position_side
            position_side_kwargs = determine_position_side(executor, direction, account_assets)

            executor.logger.info(
                f"{symbol} {direction.value} {needed_volume}, 当前={current_volume}, 目标={target_volume}"
            )

            try:
                # 使用工具函数提交和跟踪订单
                order = submit_and_track_order(
                    executor,
                    tracker,
                    direction,
                    order_type,
                    needed_volume,
                    price,
                    target_volume=float(target_volume),
                    current_volume=float(current_volume),
                    **position_side_kwargs,
                )
                if order is None:
                    execution_memory[f"{symbol}_skipped"] = "sub_min_notional"
                else:
                    execution_memory[f"{symbol}_adjustment"] = {
                        "from": current_volume,
                        "to": target_volume,
                        "diff": target_volume - current_volume,
                        "direction": direction.value,
                        "volume": needed_volume,
                        "order_id": order.order_id,
                    }
            except MemoryError:
                executor.logger.exception(f"{symbol} 下单遇到不可恢复异常")
                raise
            except RECOVERABLE_ALGORITHM_EXCEPTIONS as e:
                error_message = format_exception_message(e)
                executor.logger.error(f"{symbol} 下单失败: {error_message}")
                execution_memory[f"{symbol}_error"] = error_message

            # 等待订单完成
            tracker.wait_for_completion(timeout=max_wait_seconds)

            # 重新获取账户资产
            account_assets = executor.get_account_assets()

    finally:
        # 使用工具函数清理订单跟踪器
        teardown_order_tracker(executor, tracker, chase_config)

    orders = tracker.get_all_orders()
    trades = tracker.get_all_trades()

    return AlgorithmResult(
        orders=orders,
        trades=trades,
        account_assets=account_assets,
        target_volume=target_volume,
        first_tick=first_tick,
        memory={
            "algorithm": algorithm_name,
            "target_volume": algorithm_input.target_volume,
            "execution_details": execution_memory,
            "symbols_processed": 1,
            "orders_generated": len(orders),
            "trades_generated": len(trades),
            "total_asset": account_assets.total_asset,
            "chase_enabled": chase_config is not None,
        },
    )

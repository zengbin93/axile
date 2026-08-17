"""
算法工具模块.

提供统一的订单跟踪、等待机制和公共数据结构，自动适配不同执行器能力。
"""

from axile.executor.algorithms.utils.clock import (
    Clock,
    RealClock,
    clock_now,
    clock_now_iso,
    clock_now_ms,
    get_default_clock,
    set_default_clock,
)
from axile.executor.algorithms.utils.order_helper import (
    OrderDecision,
    determine_position_side,
    resolve_reduce_intent,
    setup_order_tracker,
    submit_and_track_order,
    teardown_order_tracker,
)
from axile.executor.algorithms.utils.order_tracker import ChaseConfig, OrderTracker
from axile.executor.algorithms.utils.trading import (
    create_empty_result,
    determine_order_price,
)

__all__ = [
    # 时钟抽象
    "Clock",
    "RealClock",
    "clock_now",
    "clock_now_iso",
    "clock_now_ms",
    "get_default_clock",
    "set_default_clock",
    # 订单跟踪
    "ChaseConfig",
    "OrderTracker",
    # 订单辅助
    "OrderDecision",
    "determine_position_side",
    "resolve_reduce_intent",
    "setup_order_tracker",
    "submit_and_track_order",
    "teardown_order_tracker",
    # 交易工具
    "create_empty_result",
    "determine_order_price",
]

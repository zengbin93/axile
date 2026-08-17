"""axile 公共 API.

本包重新导出核心交易模型和算法构建块，以便算法实现（例如 `executor/algorithms/defaults/*`）
可以使用简洁的导入语句，如 `from axile import ...`。
"""

# 交易渠道
from axile.common.trade_channel import TradeChannel

# 算法通用参数
from axile.executor.algorithms.common.params import BaseAlgorithmParams, ChaseParamsMixin

# 算法核心（注册表 / 协议）
from axile.executor.algorithms.core.base import (
    AlgorithmFunc,
    AlgorithmInput,
    AlgorithmMetadata,
    AlgorithmResult,
    AlgorithmSlot,
    ExecutorProtocol,
    get_algorithm,
    get_algorithm_metadata,
    list_algorithms,
    list_algorithms_metadata,
    register_algorithm,
    resolve_algorithm,
)
from axile.executor.algorithms.core.loader import load_algorithm_modules, load_entrypoint_algorithms

# 算法工具
from axile.executor.algorithms.utils import (
    ChaseConfig,
    OrderTracker,
    create_empty_result,
    determine_order_price,
)

# 统一模型
from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.executor.models.unified_input import UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData

# 友好别名
load_algorithms = load_algorithm_modules

__all__ = [
    # 交易渠道
    "TradeChannel",
    # 统一模型
    "UnifiedStandardInput",
    "UnifiedAccountAssets",
    "UnifiedOrder",
    "UnifiedPriceData",
    "Position",
    "PositionDirection",
    "OrderDirection",
    "OrderType",
    # 算法核心
    "AlgorithmFunc",
    "AlgorithmInput",
    "AlgorithmMetadata",
    "AlgorithmSlot",
    "AlgorithmResult",
    "ExecutorProtocol",
    "register_algorithm",
    "resolve_algorithm",
    "get_algorithm",
    "get_algorithm_metadata",
    "list_algorithms",
    "list_algorithms_metadata",
    "load_algorithm_modules",
    "load_algorithms",
    "load_entrypoint_algorithms",
    # 算法通用参数
    "BaseAlgorithmParams",
    "ChaseParamsMixin",
    # 算法工具
    "ChaseConfig",
    "OrderTracker",
    "create_empty_result",
    "determine_order_price",
]

"""
QMT 执行器模块.

对外导出 QMT 渠道执行器、回调核心组件以及原始数据到统一模型的转换函数。
"""

from axile.executor.qmt.converters import (
    convert_qmt_order_status_to_string,
    convert_qmt_order_to_unified,
    convert_qmt_order_type_to_direction,
    convert_qmt_price_type_to_order_type,
    convert_qmt_tick_to_unified_price,
    convert_qmt_trade_to_trade_record,
)
from axile.executor.qmt.core import QMTCallbackDispatcher, QMTTraderCallback
from axile.executor.qmt.core.qmt_client import (
    close_exe_window,
    find_exe_window,
    initialize_qmt,
    start_qmt_exe,
    wait_qmt_ready,
)
from axile.executor.qmt.qmt_execute import QMTExecutor, get_ticks

__all__ = [
    # 主执行器
    "QMTExecutor",
    # 核心组件
    "QMTCallbackDispatcher",
    "QMTTraderCallback",
    # 工具函数
    "find_exe_window",
    "close_exe_window",
    "wait_qmt_ready",
    "initialize_qmt",
    "start_qmt_exe",
    "get_ticks",
    # 转换器
    "convert_qmt_order_to_unified",
    "convert_qmt_trade_to_trade_record",
    "convert_qmt_order_type_to_direction",
    "convert_qmt_price_type_to_order_type",
    "convert_qmt_order_status_to_string",
    "convert_qmt_tick_to_unified_price",
]

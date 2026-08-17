"""CTP 包导出."""

from __future__ import annotations

from importlib import import_module

__version__ = "1.0.0"
__author__ = "OpenCTP Team"

__all__ = [
    # 核心执行功能
    "execute",
    "empty_positions",
    "CtpTrader",
    "CtpMarketData",
    "get_account_assets",
    # 临时文件清理功能
    "clean_ctp_temp_files",
    "auto_clean_on_exit",
    # 数据结构转换功能
    "to_dict",
    "to_dict_list",
    "CtpConverter",
    # Pydantic模型
    "OrderField",
    "TradeField",
    "PositionField",
    "TradingAccountField",
    "InstrumentField",
    "DepthMarketDataField",
    # 枚举类型
    "DirectionType",
    "OffsetFlagType",
    "OrderPriceType",
    "OrderStatusType",
    "TimeConditionType",
    "VolumeConditionType",
]

_EXPORT_MAP = {
    "execute": ("axile.executor.ctp.ctp_execute", "execute"),
    "empty_positions": ("axile.executor.ctp.ctp_execute", "empty_positions"),
    "CtpTrader": ("axile.executor.ctp.core.trader", "CtpTrader"),
    "CtpMarketData": ("axile.executor.ctp.core.market_data", "CtpMarketData"),
    "get_account_assets": ("axile.executor.ctp.utils.data_converter", "get_account_assets"),
    "clean_ctp_temp_files": ("axile.executor.ctp.utils.temp_cleaner", "clean_ctp_temp_files"),
    "auto_clean_on_exit": ("axile.executor.ctp.utils.temp_cleaner", "auto_clean_on_exit"),
    "to_dict": ("axile.executor.ctp.core.objects", "to_dict"),
    "to_dict_list": ("axile.executor.ctp.core.objects", "to_dict_list"),
    "CtpConverter": ("axile.executor.ctp.core.objects", "CtpConverter"),
    "OrderField": ("axile.executor.ctp.core.objects", "OrderField"),
    "TradeField": ("axile.executor.ctp.core.objects", "TradeField"),
    "PositionField": ("axile.executor.ctp.core.objects", "PositionField"),
    "TradingAccountField": ("axile.executor.ctp.core.objects", "TradingAccountField"),
    "InstrumentField": ("axile.executor.ctp.core.objects", "InstrumentField"),
    "DepthMarketDataField": ("axile.executor.ctp.core.objects", "DepthMarketDataField"),
    "DirectionType": ("axile.executor.ctp.core.objects", "DirectionType"),
    "OffsetFlagType": ("axile.executor.ctp.core.objects", "OffsetFlagType"),
    "OrderPriceType": ("axile.executor.ctp.core.objects", "OrderPriceType"),
    "OrderStatusType": ("axile.executor.ctp.core.objects", "OrderStatusType"),
    "TimeConditionType": ("axile.executor.ctp.core.objects", "TimeConditionType"),
    "VolumeConditionType": ("axile.executor.ctp.core.objects", "VolumeConditionType"),
}


def __getattr__(name: str) -> object:
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORT_MAP[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

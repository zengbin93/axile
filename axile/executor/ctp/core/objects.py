# -*- coding: utf-8 -*-
"""
CTP数据结构对象转换模块.

该模块提供OpenCTP API中所有数据结构对象到Python字典的转换功能，
以及使用Pydantic重新封装以提高代码可读性。

主要功能:
1. to_dict() - 将CTP数据结构对象转换为Python字典
2. Pydantic模型 - 重新封装常用数据结构
3. 类型验证和文档化
"""

from datetime import datetime
from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from axile.common.trade_channel import TradeChannel

# 导入统一订单模型
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder

# ============================================================================
# 通用转换函数
# ============================================================================


def _clock_now_iso() -> str:
    """
    返回当前 ISO 格式时间字符串.

    Returns
    -------
    str
        当前时间对应的 ISO 8601 字符串。
    """
    return datetime.now().isoformat()


def to_dict(ctp_obj: object, exclude_private: bool = True) -> dict[str, Any]:
    """
    将CTP数据结构对象转换为Python字典.

    Parameters
    ----------
    ctp_obj : object
        CTP 数据结构对象。
    exclude_private : bool, default=True
        是否排除私有属性，例如以下划线开头或 ``thisown`` 的属性。

    Returns
    -------
    dict[str, Any]
        转换后的字典。
    """
    if ctp_obj is None:
        return {}

    result: dict[str, Any] = {}

    # 获取对象的所有属性
    for attr_name in dir(ctp_obj):
        # 排除私有属性和方法
        if exclude_private:
            if attr_name.startswith("_") or attr_name == "thisown":
                continue
            # 排除方法
            attr_value = getattr(ctp_obj, attr_name)
            if callable(attr_value):
                continue

        try:
            attr_value = getattr(ctp_obj, attr_name)

            # 处理不同数据类型
            if isinstance(attr_value, str):
                result[attr_name] = attr_value
            elif isinstance(attr_value, (int, float)):
                result[attr_name] = attr_value
            elif attr_value is None:
                result[attr_name] = None
            else:
                # 对于其他类型，尝试转换为字符串
                result[attr_name] = str(attr_value)

        except (AttributeError, UnicodeDecodeError):
            # 忽略无法访问的属性
            continue

    return result


def to_dict_list(ctp_obj_list: list[object]) -> list[dict[str, Any]]:
    """
    将CTP数据结构对象列表转换为字典列表.

    Parameters
    ----------
    ctp_obj_list : list[object]
        CTP 数据结构对象列表。

    Returns
    -------
    list[dict[str, Any]]
        转换后的字典列表。
    """
    if not ctp_obj_list:
        return []

    return [to_dict(obj) for obj in ctp_obj_list]


# ============================================================================
# CTP常用数据类型枚举
# ============================================================================


class DirectionType(str, Enum):
    """买卖方向类型."""

    BUY = "0"  # 买
    SELL = "1"  # 卖


direction_map: dict[str, str] = {
    "0": "买",  # DirectionType.BUY
    "1": "卖",  # DirectionType.SELL
}


class OffsetFlagType(str, Enum):
    """开平标志类型."""

    OPEN = "0"  # 开仓
    CLOSE = "1"  # 平仓
    FORCE_CLOSE = "2"  # 强平
    CLOSE_TODAY = "3"  # 平今
    CLOSE_YESTERDAY = "4"  # 平昨
    FORCE_OFF = "5"  # 强减
    LOCAL_FORCE_CLOSE = "6"  # 本地强平


offset_flag_map: dict[str, str] = {
    "0": "开仓",  # OffsetFlagType.OPEN
    "1": "平仓",  # OffsetFlagType.CLOSE
    "2": "强平",  # OffsetFlagType.FORCE_CLOSE
    "3": "平今",  # OffsetFlagType.CLOSE_TODAY
    "4": "平昨",  # OffsetFlagType.CLOSE_YESTERDAY
    "5": "强减",  # OffsetFlagType.FORCE_OFF
    "6": "本地强平",  # OffsetFlagType.LOCAL_FORCE_CLOSE
}


class OrderPriceType(str, Enum):
    """报单价格条件类型."""

    ANY_PRICE = "1"  # 任意价
    LIMIT_PRICE = "2"  # 限价
    BEST_PRICE = "3"  # 最优价
    LAST_PRICE = "4"  # 最新价
    LAST_PRICE_PLUS_ONE = "5"  # 最新价浮动上浮1个ticks
    LAST_PRICE_PLUS_TWO = "6"  # 最新价浮动上浮2个ticks
    LAST_PRICE_PLUS_THREE = "7"  # 最新价浮动上浮3个ticks
    ASK_PRICE1 = "8"  # 卖一价
    ASK_PRICE1_PLUS_ONE = "9"  # 卖一价浮动上浮1个ticks
    ASK_PRICE1_PLUS_TWO = "A"  # 卖一价浮动上浮2个ticks
    ASK_PRICE1_PLUS_THREE = "B"  # 卖一价浮动上浮3个ticks
    BID_PRICE1 = "C"  # 买一价
    BID_PRICE1_PLUS_ONE = "D"  # 买一价浮动上浮1个ticks
    BID_PRICE1_PLUS_TWO = "E"  # 买一价浮动上浮2个ticks
    BID_PRICE1_PLUS_THREE = "F"  # 买一价浮动上浮3个ticks
    FIVE_LEVEL_PRICE = "G"  # 五档价


order_price_type_map: dict[str, str] = {
    "1": "任意价",  # OrderPriceType.ANY_PRICE
    "2": "限价",  # OrderPriceType.LIMIT_PRICE
    "3": "最优价",  # OrderPriceType.BEST_PRICE
    "4": "最新价",  # OrderPriceType.LAST_PRICE
    "5": "最新价浮动上浮1个ticks",  # OrderPriceType.LAST_PRICE_PLUS_ONE
    "6": "最新价浮动上浮2个ticks",  # OrderPriceType.LAST_PRICE_PLUS_TWO
    "7": "最新价浮动上浮3个ticks",  # OrderPriceType.LAST_PRICE_PLUS_THREE
    "8": "卖一价",  # OrderPriceType.ASK_PRICE1
    "9": "卖一价浮动上浮1个ticks",  # OrderPriceType.ASK_PRICE1_PLUS_ONE
    "A": "卖一价浮动上浮2个ticks",  # OrderPriceType.ASK_PRICE1_PLUS_TWO
    "B": "卖一价浮动上浮3个ticks",  # OrderPriceType.ASK_PRICE1_PLUS_THREE
    "C": "买一价",  # OrderPriceType.BID_PRICE1
    "D": "买一价浮动上浮1个ticks",  # OrderPriceType.BID_PRICE1_PLUS_ONE
    "E": "买一价浮动上浮2个ticks",  # OrderPriceType.BID_PRICE1_PLUS_TWO
    "F": "买一价浮动上浮3个ticks",  # OrderPriceType.BID_PRICE1_PLUS_THREE
    "G": "五档价",  # OrderPriceType.FIVE_LEVEL_PRICE
}


class OrderStatusType(str, Enum):
    """报单状态类型."""

    ALL_TRADED = "0"  # 全部成交
    PART_TRADED_QUEUEING = "1"  # 部分成交还在队列中
    PART_TRADED_NOT_QUEUEING = "2"  # 部分成交不在队列中
    NO_TRADE_QUEUEING = "3"  # 未成交还在队列中
    NO_TRADE_NOT_QUEUEING = "4"  # 未成交不在队列中
    CANCELED = "5"  # 撤单
    UNKNOWN = "a"  # 未知
    NOT_TOUCHED = "b"  # 尚未触发
    TOUCHED = "c"  # 已触发


order_status_map: dict[str, str] = {
    "0": "全部成交",  # OrderStatusType.ALL_TRADED
    "1": "部分成交还在队列中",  # OrderStatusType.PART_TRADED_QUEUEING
    "2": "部分成交不在队列中",  # OrderStatusType.PART_TRADED_NOT_QUEUEING
    "3": "未成交还在队列中",  # OrderStatusType.NO_TRADE_QUEUEING
    "4": "未成交不在队列中",  # OrderStatusType.NO_TRADE_NOT_QUEUEING
    "5": "撤单",  # OrderStatusType.CANCELED
    "a": "未知",  # OrderStatusType.UNKNOWN
    "b": "尚未触发",  # OrderStatusType.NOT_TOUCHED
    "c": "已触发",  # OrderStatusType.TOUCHED
}


class TimeConditionType(str, Enum):
    """有效期类型."""

    IOC = "1"  # 立即完成，否则撤销
    GFS = "2"  # 本节有效
    GFD = "3"  # 当日有效
    GTD = "4"  # 指定日期前有效
    GTC = "5"  # 撤销前有效
    GFA = "6"  # 集合竞价有效

    def __str__(self) -> str:
        """返回中文有效期描述."""
        return time_condition_map.get(self.value, self.value)


time_condition_map: dict[str, str] = {
    "1": "立即完成，否则撤销",  # TimeConditionType.IOC
    "2": "本节有效",  # TimeConditionType.GFS
    "3": "当日有效",  # TimeConditionType.GFD
    "4": "指定日期前有效",  # TimeConditionType.GTD
    "5": "撤销前有效",  # TimeConditionType.GTC
    "6": "集合竞价有效",  # TimeConditionType.GFA
}


class VolumeConditionType(str, Enum):
    """成交量类型."""

    ANY = "1"  # 任何数量
    MIN = "2"  # 最小数量
    ALL = "3"  # 全部数量

    def __str__(self) -> str:
        """返回中文成交量描述."""
        return volume_condition_map.get(self.value, self.value)


volume_condition_map: dict[str, str] = {
    "1": "任何数量",  # VolumeConditionType.ANY
    "2": "最小数量",  # VolumeConditionType.MIN
    "3": "全部数量",  # VolumeConditionType.ALL
}


class CancelOrderStatusType(str, Enum):
    """撤单状态类型."""

    PENDING = "pending"  # 撤单请求已发送，等待处理
    ACCEPTED = "accepted"  # 撤单请求已被接受
    REJECTED = "rejected"  # 撤单请求被拒绝
    SUCCESS = "success"  # 撤单成功
    FAILED = "failed"  # 撤单失败
    TIMEOUT = "timeout"  # 撤单超时
    UNKNOWN = "unknown"  # 未知状态

    def __str__(self) -> str:
        """返回中文撤单状态描述."""
        return cancel_order_status_map.get(self.value, self.value)


cancel_order_status_map: dict[str, str] = {
    "pending": "撤单请求已发送，等待处理",  # CancelOrderStatusType.PENDING
    "accepted": "撤单请求已被接受",  # CancelOrderStatusType.ACCEPTED
    "rejected": "撤单请求被拒绝",  # CancelOrderStatusType.REJECTED
    "success": "撤单成功",  # CancelOrderStatusType.SUCCESS
    "failed": "撤单失败",  # CancelOrderStatusType.FAILED
    "timeout": "撤单超时",  # CancelOrderStatusType.TIMEOUT
    "unknown": "未知状态",  # CancelOrderStatusType.UNKNOWN
}


class TradeType(str, Enum):
    """成交类型."""

    COMMON = "0"  # 普通成交
    OPTIONS_EXECUTION = "1"  # 期权执行
    OTC = "2"  # OTC成交
    EFP_DERIVED = "3"  # EFP成交衍生
    COMBINATION_DERIVED = "4"  # 组合衍生成交


class PosiDirection(str, Enum):
    """持仓多空方向."""

    NET = "1"  # 净持仓
    LONG = "2"  # 多头
    SHORT = "3"  # 空头


class HedgeFlag(str, Enum):
    """投机套保标志."""

    SPECULATION = "1"  # 投机
    ARBITRAGE = "2"  # 套利
    HEDGE = "3"  # 套保


trade_type_map: dict[str, str] = {
    "0": "普通成交",  # TradeType.COMMON
    "1": "期权执行",  # TradeType.OPTIONS_EXECUTION
    "2": "OTC成交",  # TradeType.OTC
    "3": "EFP成交衍生",  # TradeType.EFP_DERIVED
    "4": "组合衍生成交",  # TradeType.COMBINATION_DERIVED
}

posi_direction_map: dict[str, str] = {
    "1": "净持仓",  # PosiDirection.NET
    "2": "多头",  # PosiDirection.LONG
    "3": "空头",  # PosiDirection.SHORT
}

hedge_flag_map: dict[str, str] = {
    "1": "投机",  # HedgeFlag.SPECULATION
    "2": "套利",  # HedgeFlag.ARBITRAGE
    "3": "套保",  # HedgeFlag.HEDGE
}

# ============================================================================
# UnifiedOrder转换辅助函数
# ============================================================================


def ctp_status_to_unified(ctp_status: OrderStatusType | str) -> str:
    """CTP订单状态转换为统一状态字符串."""
    # 将字符串转换为枚举
    status_enum = OrderStatusType(ctp_status) if not isinstance(ctp_status, OrderStatusType) else ctp_status

    status_map = {
        OrderStatusType.ALL_TRADED: "已成交",
        OrderStatusType.PART_TRADED_QUEUEING: "部分成交",
        OrderStatusType.PART_TRADED_NOT_QUEUEING: "部分成交",
        OrderStatusType.NO_TRADE_QUEUEING: "已报",
        OrderStatusType.NO_TRADE_NOT_QUEUEING: "已报",
        OrderStatusType.CANCELED: "已撤销",
    }
    return status_map.get(status_enum, "未知状态")


# ============================================================================
# 撤单相关数据结构
# ============================================================================


class CancelOrderRequest(BaseModel):
    """撤单请求数据结构."""

    request_id: str = Field(..., description="撤单请求ID")
    order_sys_id: str = Field(default="", description="系统报单编号")
    order_ref: str = Field(default="", description="报单引用")
    front_id: int = Field(default=0, description="前置编号")
    session_id: int = Field(default=0, description="会话编号")
    exchange_id: str = Field(default="", description="交易所代码")
    instrument_id: str = Field(default="", description="合约代码")
    timestamp: float = Field(default_factory=lambda: __import__("time").time(), description="请求时间戳")
    status: CancelOrderStatusType = Field(default=CancelOrderStatusType.PENDING, description="撤单状态")
    error_code: int = Field(default=0, description="错误代码")
    error_msg: str = Field(default="", description="错误信息")


class CancelOrderResult(BaseModel):
    """撤单结果数据结构."""

    request_id: str = Field(..., description="撤单请求ID")
    order_sys_id: str = Field(default="", description="系统报单编号")
    order_ref: str = Field(default="", description="报单引用")
    exchange_id: str = Field(default="", description="交易所代码")
    instrument_id: str = Field(default="", description="合约代码")
    status: CancelOrderStatusType = Field(..., description="撤单最终状态")
    success: bool = Field(..., description="是否成功")
    error_code: int = Field(default=0, description="错误代码")
    error_msg: str = Field(default="", description="错误信息")
    response_time: float = Field(default_factory=lambda: __import__("time").time(), description="响应时间戳")


# ============================================================================
# Pydantic模型定义 - 核心数据结构
# ============================================================================


class BaseCtpModel(BaseModel):
    """CTP基础模型."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        use_enum_values=True,
        validate_by_name=True,
    )


# ----------------------------------------------------------------------------
# 交易相关数据结构
# ----------------------------------------------------------------------------


class OrderField(BaseCtpModel):
    """报单信息."""

    BrokerID: str = Field("", description="经纪公司代码")
    InvestorID: str = Field("", description="投资者代码")
    InstrumentID: str = Field("", description="合约代码")
    OrderRef: str = Field("", description="报单引用")
    UserID: str = Field("", description="用户代码")
    OrderPriceType: str = Field("2", description="报单价格条件")
    Direction: str = Field("0", description="买卖方向")
    CombOffsetFlag: str = Field("", description="组合开平标志")
    CombHedgeFlag: str = Field("", description="组合投机套保标志")
    LimitPrice: float = Field(0.0, description="价格")
    VolumeTotalOriginal: int = Field(0, description="数量")
    TimeCondition: str = Field("3", description="有效期类型")
    GTDDate: str = Field("", description="GTD日期")
    VolumeCondition: str = Field("1", description="成交量类型")
    MinVolume: int = Field(1, description="最小成交量")
    ContingentCondition: str = Field("", description="触发条件")
    StopPrice: float = Field(0.0, description="止损价")
    ForceCloseReason: str = Field("", description="强平原因")
    IsAutoSuspend: int = Field(0, description="自动挂起标志")
    BusinessUnit: str = Field("", description="业务单元")
    RequestID: int = Field(0, description="请求编号")
    OrderLocalID: str = Field("", description="本地报单编号")
    ExchangeID: str = Field("", description="交易所代码")
    ParticipantID: str = Field("", description="会员代码")
    ClientID: str = Field("", description="客户代码")
    ExchangeInstID: str = Field("", description="合约在交易所的代码")
    TraderID: str = Field("", description="交易所交易员代码")
    InstallID: int = Field(0, description="安装编号")
    OrderSubmitStatus: str = Field("", description="报单提交状态")
    NotifySequence: int = Field(0, description="报单提示序号")
    TradingDay: str = Field("", description="交易日")
    SettlementID: int = Field(0, description="结算编号")
    OrderSysID: str = Field("", description="报单编号")
    OrderSource: str = Field("", description="报单来源")
    OrderStatus: str = Field("a", description="报单状态")
    OrderType: str = Field("", description="报单类型")
    VolumeTraded: int = Field(0, description="今成交数量")
    VolumeTotal: int = Field(0, description="剩余数量")
    InsertDate: str = Field("", description="报单日期")
    InsertTime: str = Field("", description="委托时间")
    ActiveTime: str = Field("", description="激活时间")
    SuspendTime: str = Field("", description="挂起时间")
    UpdateTime: str = Field("", description="最后修改时间")
    CancelTime: str = Field("", description="撤销时间")
    ActiveTraderID: str = Field("", description="最后修改交易所交易员代码")
    ClearingPartID: str = Field("", description="结算会员编号")
    SequenceNo: int = Field(0, description="序号")
    FrontID: int = Field(0, description="前置编号")
    SessionID: int = Field(0, description="会话编号")
    UserProductInfo: str = Field("", description="用户端产品信息")
    StatusMsg: str = Field("", description="状态信息")
    UserForceClose: int = Field(0, description="用户强平标志")
    ActiveUserID: str = Field("", description="操作用户代码")
    BrokerOrderSeq: int = Field(0, description="经纪公司报单编号")
    RelativeOrderSysID: str = Field("", description="相关报单")
    ZCETotalTradedVolume: int = Field(0, description="郑商所成交数量")
    IsSwapOrder: int = Field(0, description="互换单标志")
    BranchID: str = Field("", description="营业部编号")
    InvestUnitID: str = Field("", description="投资单元代码")
    AccountID: str = Field("", description="资金账号")
    CurrencyID: str = Field("", description="币种代码")
    IPAddress: str = Field("", description="IP地址")
    MacAddress: str = Field("", description="Mac地址")

    @classmethod
    def from_ctp(cls, ctp_order: object) -> "OrderField":
        """从CTP报单对象创建."""
        if ctp_order is None:
            return cls.model_construct()  # 使用默认值构造空实例
        return cls(**to_dict(ctp_order))

    def __str__(self) -> str:
        """自定义字符串表示."""
        order_type = order_price_type_map.get(self.OrderPriceType, self.OrderPriceType)
        order_status = order_status_map.get(self.OrderStatus, self.OrderStatus)
        order_direction = direction_map.get(self.Direction, self.Direction)
        offset_flag = offset_flag_map.get(self.CombOffsetFlag, self.CombOffsetFlag)

        _s = f"Order 订单详情 - {self.OrderSysID}"
        _s += f"\n  合约: {self.ExchangeID}.{self.InstrumentID}"
        _s += f"\n  类型: {order_type} ({self.OrderPriceType})"
        _s += f"\n  方向: {order_direction} ({self.Direction})"
        _s += f"\n  开平: {offset_flag} ({self.CombOffsetFlag})"
        _s += f"\n  数量: {self.VolumeTotal} (已成交: {self.VolumeTraded})"
        _s += f"\n  价格: {self.LimitPrice:.2f}"
        _s += f"\n  状态: {order_status} ({self.OrderStatus})"
        _s += f"\n  时间: {self.InsertTime} (日期: {self.InsertDate})"
        return _s

    def to_unified(self) -> UnifiedOrder:
        """将CTP OrderField转换为UnifiedOrder."""
        # 处理时间
        try:
            dt = pd.to_datetime(f"{self.TradingDay} {self.InsertTime}", format="%Y%m%d %H:%M:%S")
            if self.InsertTime >= "15:00:00":
                dt -= pd.Timedelta(days=1)
            create_time = dt.isoformat()
        except Exception:
            # 如果时间解析失败，使用当前时间
            create_time = _clock_now_iso()

        # 转换枚举
        direction_enum = OrderDirection.BUY if self.Direction == DirectionType.BUY else OrderDirection.SELL
        order_type_enum = OrderType.LIMIT if self.OrderPriceType == OrderPriceType.LIMIT_PRICE else OrderType.MARKET

        unified_order = UnifiedOrder.model_construct(
            order_id=self.OrderSysID or self.OrderRef,  # 如果没有OrderSysID，使用OrderRef
            symbol=self.InstrumentID,
            direction=direction_enum,
            order_type=order_type_enum,
            volume=float(self.VolumeTotalOriginal),
            price=float(self.LimitPrice),
            status=ctp_status_to_unified(self.OrderStatus),
            filled_volume=float(self.VolumeTraded),
            create_time=create_time,
            update_time=create_time,
            extra={
                "channel_type": TradeChannel.CTP,
                "raw_order_data": self.model_dump(),
                "order_ref": self.OrderRef,
                "exchange_id": self.ExchangeID,
                "investor_id": self.InvestorID,
                "broker_id": self.BrokerID,
                "direction": self.Direction,
                "offset": self.CombOffsetFlag,
                "volume_left": float(self.VolumeTotal),
                "status_msg": self.StatusMsg,
                "front_id": self.FrontID,
                "session_id": self.SessionID,
                "insert_time": self.InsertTime,
                "update_time": self.UpdateTime,
                "cancel_time": self.CancelTime,
                # 保留原有的描述信息
                "direction_desc": "买" if self.Direction == DirectionType.BUY else "卖",
                "offset_desc": offset_flag_map.get(self.CombOffsetFlag, self.CombOffsetFlag),
                "status_desc": order_status_map.get(self.OrderStatus, self.OrderStatus),
            },
        )

        # 计算成交均价（如果有成交）
        if self.VolumeTraded > 0:
            unified_order.avg_price = 0.0  # 需要结合成交记录计算

        return unified_order


class TradeField(BaseCtpModel):
    """成交信息."""

    BrokerID: str = Field("", description="经纪公司代码")
    InvestorID: str = Field("", description="投资者代码")
    InstrumentID: str = Field("", description="合约代码")
    OrderRef: str = Field("", description="报单引用")
    UserID: str = Field("", description="用户代码")
    ExchangeID: str = Field("", description="交易所代码")
    TradeID: str = Field("", description="成交编号")
    Direction: str = Field("0", description="买卖方向")
    OrderSysID: str = Field("", description="报单编号")
    ParticipantID: str = Field("", description="会员代码")
    ClientID: str = Field("", description="客户代码")
    TradingRole: str = Field("", description="交易角色")
    ExchangeInstID: str = Field("", description="合约在交易所的代码")
    OffsetFlag: str = Field("0", description="开平标志")
    HedgeFlag: str = Field("", description="投机套保标志")
    Price: float = Field(0.0, description="价格")
    Volume: int = Field(0, description="数量")
    TradeDate: str = Field("", description="成交时期")
    TradeTime: str = Field("", description="成交时间")
    TradeType: str = Field("", description="成交类型")
    PriceSource: str = Field("", description="成交价来源")
    TraderID: str = Field("", description="交易所交易员代码")
    OrderLocalID: str = Field("", description="本地报单编号")
    ClearingPartID: str = Field("", description="结算会员编号")
    BusinessUnit: str = Field("", description="业务单元")
    SequenceNo: int = Field(0, description="序号")
    TradingDay: str = Field("", description="交易日")
    SettlementID: int = Field(0, description="结算编号")
    BrokerOrderSeq: int = Field(0, description="经纪公司报单编号")
    TradeSource: str = Field("", description="成交来源")
    InvestUnitID: str = Field("", description="投资单元代码")

    @classmethod
    def from_ctp(cls, ctp_trade: object) -> "TradeField":
        """从CTP成交对象创建."""
        if ctp_trade is None:
            return cls.model_construct()  # 使用默认值构造空实例
        return cls(**to_dict(ctp_trade))

    def __str__(self) -> str:
        """自定义字符串表示."""
        direction = direction_map.get(self.Direction, self.Direction)
        offset_flag = offset_flag_map.get(self.OffsetFlag, self.OffsetFlag)
        trade_type = trade_type_map.get(self.TradeType, self.TradeType)
        hedge_flag = hedge_flag_map.get(self.HedgeFlag, self.HedgeFlag)

        _s = f"Trade 成交详情 - {self.TradeID}"
        _s += f"\n  合约: {self.ExchangeID}.{self.InstrumentID}"
        _s += f"\n  方向: {direction} ({self.Direction})"
        _s += f"\n  开平: {offset_flag} ({self.OffsetFlag})"
        _s += f"\n  套保: {hedge_flag}（{self.HedgeFlag}）"
        _s += f"\n  数量: {self.Volume}"
        _s += f"\n  价格: {self.Price:.2f}"
        _s += f"\n  类型: {trade_type}（{self.TradeType}）"
        _s += f"\n  时间: {self.TradeTime} (日期: {self.TradeDate})"
        return _s

    def to_unified_trade(self) -> TradeRecord:
        """将CTP TradeField转换为TradeRecord."""
        # 解析成交时间（处理跨日期问题）
        try:
            dt = pd.to_datetime(f"{self.TradingDay} {self.TradeTime}", format="%Y%m%d %H:%M:%S")
            if self.TradeTime >= "15:00:00":
                dt -= pd.Timedelta(days=1)
            trade_time = dt.isoformat()
        except Exception:
            # 如果时间解析失败，使用当前时间
            trade_time = _clock_now_iso()

        # 计算成交金额
        trade_value = float(self.Volume) * float(self.Price)

        # 创建成交记录
        return TradeRecord(
            trade_id=self.TradeID,
            symbol=self.InstrumentID,
            order_id=self.OrderSysID,
            trade_time=trade_time,
            trade_volume=float(self.Volume),
            trade_price=float(self.Price),
            trade_value=trade_value,
            extra={
                "channel_type": TradeChannel.CTP,
                "raw_trade_data": self.model_dump(),
                "order_id": self.OrderSysID,
                "order_ref": self.OrderRef,
                "direction": self.Direction,
                "offset": self.OffsetFlag,
                "exchange_id": self.ExchangeID,
                "trade_date": self.TradeDate,
                "trade_time": self.TradeTime,
                "trade_type": self.TradeType,
                "hedge_flag": self.HedgeFlag,
                # 保留原有的描述信息
                "direction_desc": "买" if self.Direction == DirectionType.BUY else "卖",
                "offset_desc": offset_flag_map.get(self.OffsetFlag, self.OffsetFlag),
                "trade_type_desc": trade_type_map.get(self.TradeType, self.TradeType),
            },
        )


class PositionField(BaseCtpModel):
    """投资者持仓信息."""

    InstrumentID: str = Field("", description="合约代码")
    BrokerID: str = Field("", description="经纪公司代码")
    InvestorID: str = Field("", description="投资者代码")
    PosiDirection: str = Field("", description="持仓多空方向")
    HedgeFlag: str = Field("", description="投机套保标志")
    PositionDate: str = Field("", description="持仓日期")
    YdPosition: int = Field(0, description="昨持仓")
    Position: int = Field(0, description="今持仓")
    LongFrozen: int = Field(0, description="多头冻结")
    ShortFrozen: int = Field(0, description="空头冻结")
    LongFrozenAmount: float = Field(0.0, description="开仓冻结金额")
    ShortFrozenAmount: float = Field(0.0, description="开仓冻结金额")
    OpenVolume: int = Field(0, description="开仓量")
    CloseVolume: int = Field(0, description="平仓量")
    OpenAmount: float = Field(0.0, description="开仓金额")
    CloseAmount: float = Field(0.0, description="平仓金额")
    PositionCost: float = Field(0.0, description="持仓成本")
    PreMargin: float = Field(0.0, description="上次占用的保证金")
    UseMargin: float = Field(0.0, description="占用的保证金")
    FrozenMargin: float = Field(0.0, description="冻结的保证金")
    FrozenCash: float = Field(0.0, description="冻结的资金")
    FrozenCommission: float = Field(0.0, description="冻结的手续费")
    CashIn: float = Field(0.0, description="资金差额")
    Commission: float = Field(0.0, description="手续费")
    CloseProfit: float = Field(0.0, description="平仓盈亏")
    PositionProfit: float = Field(0.0, description="持仓盈亏")
    PreSettlementPrice: float = Field(0.0, description="上次结算价")
    SettlementPrice: float = Field(0.0, description="本次结算价")
    TradingDay: str = Field("", description="交易日")
    SettlementID: int = Field(0, description="结算编号")
    OpenCost: float = Field(0.0, description="开仓成本")
    ExchangeMargin: float = Field(0.0, description="交易所保证金")
    CombPosition: int = Field(0, description="组合成交形成的持仓")
    CombLongFrozen: int = Field(0, description="组合多头冻结")
    CombShortFrozen: int = Field(0, description="组合空头冻结")
    CloseProfitByDate: float = Field(0.0, description="逐日盯市平仓盈亏")
    CloseProfitByTrade: float = Field(0.0, description="逐笔对冲平仓盈亏")
    TodayPosition: int = Field(0, description="今日持仓")
    MarginRateByMoney: float = Field(0.0, description="保证金率")
    MarginRateByVolume: float = Field(0.0, description="保证金率(按手数)")
    StrikeFrozen: int = Field(0, description="执行冻结")
    StrikeFrozenAmount: float = Field(0.0, description="执行冻结金额")
    AbandonFrozen: int = Field(0, description="放弃执行冻结")
    ExchangeID: str = Field("", description="交易所代码")
    YdStrikeFrozen: int = Field(0, description="执行冻结的昨仓")
    InvestUnitID: str = Field("", description="投资单元代码")

    @classmethod
    def from_ctp(cls, ctp_position: object) -> "PositionField":
        """从CTP持仓对象创建."""
        if ctp_position is None:
            return cls.model_construct()  # 使用默认值构造空实例
        return cls(**to_dict(ctp_position))

    def __str__(self) -> str:
        """自定义字符串表示."""
        posi_direction = posi_direction_map.get(self.PosiDirection, self.PosiDirection)
        hedge_flag = hedge_flag_map.get(self.HedgeFlag, self.HedgeFlag)

        _s = f"Position 持仓详情 - {self.ExchangeID}.{self.InstrumentID}"
        _s += f"\n  方向: {posi_direction}（{self.PosiDirection}）"
        _s += f"\n  套保: {hedge_flag}（{self.HedgeFlag}）"
        _s += f"\n  昨持仓: {self.YdPosition} 今持仓: {self.Position}"
        _s += f"\n  冻结多头: {self.LongFrozen} 冻结空头: {self.ShortFrozen}"
        _s += f"\n  占用保证金: {self.UseMargin:.2f}"
        _s += f"\n  持仓盈亏: {self.PositionProfit:.2f}"
        return _s


class TradingAccountField(BaseCtpModel):
    """资金账户信息."""

    BrokerID: str = Field("", description="经纪公司代码")
    AccountID: str = Field("", description="投资者帐号")
    PreMortgage: float = Field(0.0, description="上次质押金额")
    PreCredit: float = Field(0.0, description="上次信用额度")
    PreDeposit: float = Field(0.0, description="上次存款额")
    PreBalance: float = Field(0.0, description="上次结算准备金")
    PreMargin: float = Field(0.0, description="上次占用的保证金")
    InterestBase: float = Field(0.0, description="利息基数")
    Interest: float = Field(0.0, description="利息收入")
    Deposit: float = Field(0.0, description="入金金额")
    Withdraw: float = Field(0.0, description="出金金额")
    FrozenMargin: float = Field(0.0, description="冻结的保证金")
    FrozenCash: float = Field(0.0, description="冻结的资金")
    FrozenCommission: float = Field(0.0, description="冻结的手续费")
    CurrMargin: float = Field(0.0, description="当前保证金总额")
    CashIn: float = Field(0.0, description="资金差额")
    Commission: float = Field(0.0, description="手续费")
    CloseProfit: float = Field(0.0, description="平仓盈亏")
    PositionProfit: float = Field(0.0, description="持仓盈亏")
    Balance: float = Field(0.0, description="期货结算准备金")  # 总资产（现金 + 持仓市值 + 浮动盈亏）
    Available: float = Field(0.0, description="可用资金")
    WithdrawQuota: float = Field(0.0, description="可取资金")
    Reserve: float = Field(0.0, description="基本准备金")
    TradingDay: str = Field("", description="交易日")
    SettlementID: int = Field(0, description="结算编号")
    Credit: float = Field(0.0, description="信用额度")
    Mortgage: float = Field(0.0, description="质押金额")
    ExchangeMargin: float = Field(0.0, description="交易所保证金")
    DeliveryMargin: float = Field(0.0, description="投资者交割保证金")
    ExchangeDeliveryMargin: float = Field(0.0, description="交易所交割保证金")
    ReserveBalance: float = Field(0.0, description="保底期货结算准备金")
    CurrencyID: str = Field("", description="币种代码")
    PreFundMortgageIn: float = Field(0.0, description="上次货币质入金额")
    PreFundMortgageOut: float = Field(0.0, description="上次货币质出金额")
    FundMortgageIn: float = Field(0.0, description="货币质入金额")
    FundMortgageOut: float = Field(0.0, description="货币质出金额")
    FundMortgageAvailable: float = Field(0.0, description="货币质押余额")
    MortgageableFund: float = Field(0.0, description="可质押货币金额")
    SpecProductMargin: float = Field(0.0, description="特殊产品占用保证金")
    SpecProductFrozenMargin: float = Field(0.0, description="特殊产品冻结保证金")
    SpecProductCommission: float = Field(0.0, description="特殊产品手续费")
    SpecProductFrozenCommission: float = Field(0.0, description="特殊产品冻结手续费")
    SpecProductPositionProfit: float = Field(0.0, description="特殊产品持仓盈亏")
    SpecProductCloseProfit: float = Field(0.0, description="特殊产品平仓盈亏")
    SpecProductPositionProfitByAlg: float = Field(0.0, description="根据持仓盈亏算法计算的特殊产品持仓盈亏")
    SpecProductExchangeMargin: float = Field(0.0, description="特殊产品交易所保证金")
    BizType: str = Field("", description="业务类型")
    FrozenSwap: float = Field(0.0, description="延时换汇冻结金额")
    RemainSwap: float = Field(0.0, description="剩余换汇额度")

    @classmethod
    def from_ctp(cls, ctp_account: object) -> "TradingAccountField":
        """从CTP资金账户对象创建."""
        if ctp_account is None:
            return cls.model_construct()  # 使用默认值构造空实例
        return cls(**to_dict(ctp_account))

    def __str__(self) -> str:
        """自定义字符串表示."""
        _s = f"Account 资金账户 - {self.AccountID}"
        _s += f"\n  经纪公司: {self.BrokerID}"
        _s += f"\n  可用资金: {self.Available:.2f} (总资产: {self.Balance:.2f})"
        _s += f"\n  冻结保证金: {self.FrozenMargin:.2f} 冻结资金: {self.FrozenCash:.2f}"
        _s += f"\n  持仓盈亏: {self.PositionProfit:.2f} 平仓盈亏: {self.CloseProfit:.2f}"
        return _s


class InstrumentField(BaseCtpModel):
    """合约信息."""

    InstrumentID: str = Field("", description="合约代码")
    ExchangeID: str = Field("", description="交易所代码")
    InstrumentName: str = Field("", description="合约名称")
    ExchangeInstID: str = Field("", description="合约在交易所的代码")
    ProductID: str = Field("", description="产品代码")
    ProductClass: str = Field("", description="产品类型")
    DeliveryYear: int = Field(0, description="交割年份")
    DeliveryMonth: int = Field(0, description="交割月")
    MaxMarketOrderVolume: int = Field(0, description="市价单最大下单量")
    MinMarketOrderVolume: int = Field(0, description="市价单最小下单量")
    MaxLimitOrderVolume: int = Field(0, description="限价单最大下单量")
    MinLimitOrderVolume: int = Field(0, description="限价单最小下单量")
    VolumeMultiple: int = Field(1, description="合约数量乘数")
    PriceTick: float = Field(0.0, description="最小变动价位")
    CreateDate: str = Field("", description="创建日")
    OpenDate: str = Field("", description="上市日")
    ExpireDate: str = Field("", description="到期日")
    StartDelivDate: str = Field("", description="开始交割日")
    EndDelivDate: str = Field("", description="结束交割日")
    InstLifePhase: str = Field("", description="合约生命周期状态")
    IsTrading: int = Field(0, description="当前是否交易")
    PositionType: str = Field("", description="持仓类型")
    PositionDateType: str = Field("", description="持仓日期类型")
    LongMarginRatio: float = Field(0.0, description="多头保证金率")
    ShortMarginRatio: float = Field(0.0, description="空头保证金率")
    MaxMarginSideAlgorithm: str = Field("", description="是否使用大额单边保证金算法")
    UnderlyingInstrID: str = Field("", description="基础商品代码")
    StrikePrice: float = Field(0.0, description="执行价")
    OptionsType: str = Field("", description="期权类型")
    UnderlyingMultiple: float = Field(0.0, description="合约基础商品乘数")
    CombinationType: str = Field("", description="组合类型")

    @classmethod
    def from_ctp(cls, ctp_instrument: object) -> "InstrumentField":
        """从CTP合约对象创建."""
        if ctp_instrument is None:
            return cls.model_construct()  # 使用默认值构造空实例
        return cls(**to_dict(ctp_instrument))

    def __str__(self) -> str:
        """自定义字符串表示."""
        _s = f"Instrument 合约信息 - {self.InstrumentID}"
        _s += f"\n  名称: {self.InstrumentName} (交易所: {self.ExchangeID})"
        _s += f"\n  产品类型: {self.ProductClass} (代码: {self.ProductID})"
        _s += f"\n  上市日: {self.OpenDate} 到期日: {self.ExpireDate}"
        _s += f"\n  最小变动价位: {self.PriceTick:.4f} 合约乘数: {self.VolumeMultiple}"
        return _s


class DepthMarketDataField(BaseCtpModel):
    """深度行情数据."""

    TradingDay: str = Field("", description="交易日")
    InstrumentID: str = Field("", description="合约代码")
    ExchangeID: str = Field("", description="交易所代码")
    ExchangeInstID: str = Field("", description="合约在交易所的代码")
    LastPrice: float = Field(0.0, description="最新价")
    PreSettlementPrice: float = Field(0.0, description="上次结算价")
    PreClosePrice: float = Field(0.0, description="昨收盘")
    PreOpenInterest: float = Field(0.0, description="昨持仓量")
    OpenPrice: float = Field(0.0, description="今开盘")
    HighestPrice: float = Field(0.0, description="最高价")
    LowestPrice: float = Field(0.0, description="最低价")
    Volume: int = Field(0, description="数量")
    Turnover: float = Field(0.0, description="成交金额")
    OpenInterest: float = Field(0.0, description="持仓量")
    ClosePrice: float = Field(0.0, description="今收盘")
    SettlementPrice: float = Field(0.0, description="本次结算价")
    UpperLimitPrice: float = Field(0.0, description="涨停板价")
    LowerLimitPrice: float = Field(0.0, description="跌停板价")
    PreDelta: float = Field(0.0, description="昨虚实度")
    CurrDelta: float = Field(0.0, description="今虚实度")
    UpdateTime: str = Field("", description="最后修改时间")
    UpdateMillisec: int = Field(0, description="最后修改毫秒")
    BidPrice1: float = Field(0.0, description="申买价一")
    BidVolume1: int = Field(0, description="申买量一")
    AskPrice1: float = Field(0.0, description="申卖价一")
    AskVolume1: int = Field(0, description="申卖量一")
    BidPrice2: float = Field(0.0, description="申买价二")
    BidVolume2: int = Field(0, description="申买量二")
    AskPrice2: float = Field(0.0, description="申卖价二")
    AskVolume2: int = Field(0, description="申卖量二")
    BidPrice3: float = Field(0.0, description="申买价三")
    BidVolume3: int = Field(0, description="申买量三")
    AskPrice3: float = Field(0.0, description="申卖价三")
    AskVolume3: int = Field(0, description="申卖量三")
    BidPrice4: float = Field(0.0, description="申买价四")
    BidVolume4: int = Field(0, description="申买量四")
    AskPrice4: float = Field(0.0, description="申卖价四")
    AskVolume4: int = Field(0, description="申卖量四")
    BidPrice5: float = Field(0.0, description="申买价五")
    BidVolume5: int = Field(0, description="申买量五")
    AskPrice5: float = Field(0.0, description="申卖价五")
    AskVolume5: int = Field(0, description="申卖量五")
    AveragePrice: float = Field(0.0, description="当日均价")
    ActionDay: str = Field("", description="业务日期")

    @classmethod
    def from_ctp(cls, ctp_tick: object) -> "DepthMarketDataField":
        """从CTP行情对象创建."""
        if ctp_tick is None:
            return cls.model_construct()  # 使用默认值构造空实例
        return cls(**to_dict(ctp_tick))

    def __str__(self) -> str:
        """自定义字符串表示."""
        _s = f"Tick 行情数据 - {self.InstrumentID}"
        _s += f"\n  最新价: {self.LastPrice:.2f} (昨收: {self.PreClosePrice:.2f})"
        _s += f"\n  开盘: {self.OpenPrice:.2f} 最高: {self.HighestPrice:.2f} 最低: {self.LowestPrice:.2f}"
        _s += f"\n  成交量: {self.Volume} 成交额: {self.Turnover:.2f}"
        _s += f"\n  持仓量: {self.OpenInterest:.2f} (昨持仓: {self.PreOpenInterest:.2f})"
        _s += f"\n  买一: {self.BidPrice1:.2f} ({self.BidVolume1}) 卖一: {self.AskPrice1:.2f} ({self.AskVolume1})"
        _s += f"\n  买二: {self.BidPrice2:.2f} ({self.BidVolume2}) 卖二: {self.AskPrice2:.2f} ({self.AskVolume2})"
        _s += f"\n  更新时间: {self.UpdateTime}.{self.UpdateMillisec}"
        return _s


# ============================================================================
# 便捷转换函数集合
# ============================================================================


class CtpConverter:
    """CTP数据结构转换器."""

    @staticmethod
    def order_to_dict(ctp_order: object) -> dict[str, Any]:
        """报单转字典."""
        return to_dict(ctp_order)

    @staticmethod
    def trade_to_dict(ctp_trade: object) -> dict[str, Any]:
        """成交转字典."""
        return to_dict(ctp_trade)

    @staticmethod
    def position_to_dict(ctp_position: object) -> dict[str, Any]:
        """持仓转字典."""
        return to_dict(ctp_position)

    @staticmethod
    def account_to_dict(ctp_account: object) -> dict[str, Any]:
        """资金账户转字典."""
        return to_dict(ctp_account)

    @staticmethod
    def instrument_to_dict(ctp_instrument: object) -> dict[str, Any]:
        """合约转字典."""
        return to_dict(ctp_instrument)

    @staticmethod
    def tick_to_dict(ctp_tick: object) -> dict[str, Any]:
        """行情转字典."""
        return to_dict(ctp_tick)

    @staticmethod
    def order_to_model(ctp_order: object) -> OrderField:
        """报单转模型."""
        return OrderField.from_ctp(ctp_order)

    @staticmethod
    def trade_to_model(ctp_trade: object) -> TradeField:
        """成交转模型."""
        return TradeField.from_ctp(ctp_trade)

    @staticmethod
    def position_to_model(ctp_position: object) -> PositionField:
        """持仓转模型."""
        return PositionField.from_ctp(ctp_position)

    @staticmethod
    def account_to_model(ctp_account: object) -> TradingAccountField:
        """资金账户转模型."""
        return TradingAccountField.from_ctp(ctp_account)

    @staticmethod
    def instrument_to_model(ctp_instrument: object) -> InstrumentField:
        """合约转模型."""
        return InstrumentField.from_ctp(ctp_instrument)

    @staticmethod
    def tick_to_model(ctp_tick: object) -> DepthMarketDataField:
        """行情转模型."""
        return DepthMarketDataField.from_ctp(ctp_tick)


# ============================================================================
# 导出的便捷访问接口
# ============================================================================

__all__ = [
    # 基础转换函数
    "to_dict",
    "to_dict_list",
    # 枚举类型
    "DirectionType",
    "OffsetFlagType",
    "OrderPriceType",
    "OrderStatusType",
    "TimeConditionType",
    "VolumeConditionType",
    "CancelOrderStatusType",
    "TradeType",
    "PosiDirection",
    "HedgeFlag",
    # 撤单相关数据结构
    "CancelOrderRequest",
    "CancelOrderResult",
    # Pydantic模型
    "BaseCtpModel",
    "OrderField",
    "TradeField",
    "PositionField",
    "TradingAccountField",
    "InstrumentField",
    "DepthMarketDataField",
    # 转换器
    "CtpConverter",
]

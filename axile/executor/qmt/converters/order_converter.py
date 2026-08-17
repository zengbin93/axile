"""
QMT 订单数据转换器.

提供 QMT 订单数据与统一模型之间的转换功能。
"""

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

from datetime import datetime

from xtquant.xttype import XtOrder, XtTrade  # type: ignore

from axile.common.trade_channel import TradeChannel
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.unified_order import (
    OrderDirection,
    OrderType,
    TradeRecord,
    UnifiedOrder,
)


def convert_qmt_order_type_to_direction(order_type: int) -> OrderDirection:
    """
    将 QMT 委托类型转换为统一方向枚举.

    Parameters
    ----------
    order_type : int
        QMT 委托类型，例如 ``23`` 表示买入，``24`` 表示卖出。

    Returns
    -------
    OrderDirection
        统一的订单方向枚举。
    """
    if order_type == 23:  # 买入
        return OrderDirection.BUY
    elif order_type == 24:  # 卖出
        return OrderDirection.SELL
    else:
        # 默认值，可以根据实际情况调整
        return OrderDirection.BUY


def convert_qmt_price_type_to_order_type(price_type: int) -> OrderType:
    """
    将 QMT 报价类型转换为统一订单类型枚举.

    Parameters
    ----------
    price_type : int
        QMT 报价类型，例如 ``11`` 表示限价，``5`` 表示最新价。

    Returns
    -------
    OrderType
        统一的订单类型枚举。
    """
    if price_type == 11:  # 限价
        return OrderType.LIMIT
    elif price_type == 5:  # 最新价
        return OrderType.MARKET
    else:
        # 其他类型默认为限价单
        return OrderType.LIMIT


def convert_qmt_order_status_to_string(order_status: int) -> str:
    """
    将 QMT 委托状态转换为中文状态字符串.

    Parameters
    ----------
    order_status : int
        QMT 委托状态码。

    Returns
    -------
    str
        中文状态字符串。
    """
    status_map = {
        48: "未报",  # QMT特有状态
        49: "待报",  # QMT特有状态
        50: OrderStatus.SUBMITTED,
        51: "已报待撤",  # QMT特有状态
        52: "部成待撤",  # QMT特有状态
        53: "部撤",  # QMT特有状态
        54: OrderStatus.CANCELED,
        55: OrderStatus.PARTIALLY_FILLED,
        56: OrderStatus.FILLED,
        57: OrderStatus.REJECTED,  # 废单，映射为统一终态
        255: "未知",
    }
    return status_map.get(order_status, "未知")


def convert_qmt_trade_to_trade_record(qmt_trade: XtTrade) -> TradeRecord:  # type: ignore[valid-type]
    """
    将 QMT 成交记录转换为统一成交记录.

    Parameters
    ----------
    qmt_trade : XtTrade
        QMT 原始成交对象。

    Returns
    -------
    TradeRecord
        统一成交记录对象。
    """
    # 时间戳转换为ISO格式
    trade_time = datetime.fromtimestamp(qmt_trade.traded_time).isoformat()

    # 获取成交数据
    trade_volume = float(qmt_trade.traded_volume)
    trade_price = float(qmt_trade.traded_price)

    # 创建成交记录
    trade_record = TradeRecord.create(
        trade_id=str(qmt_trade.traded_id),
        symbol=qmt_trade.stock_code,
        order_id=str(qmt_trade.order_id),
        trade_time=trade_time,
        trade_volume=trade_volume,
        trade_price=trade_price,
        # 将 QMT 特有字段存储到 extra
        channel_type=TradeChannel.QMT,
        order_sysid=qmt_trade.order_sysid,
        traded_amount=float(qmt_trade.traded_amount),
        offset_flag=qmt_trade.offset_flag,
        direction=qmt_trade.direction,
        commission=getattr(qmt_trade, "commission", 0.0),
        secu_account=getattr(qmt_trade, "secu_account", ""),
        instrument_name=getattr(qmt_trade, "instrument_name", ""),
    )

    return trade_record


def convert_qmt_order_to_unified(qmt_order: XtOrder) -> UnifiedOrder:
    """
    将 QMT 订单数据转换为统一订单模型.

    Parameters
    ----------
    qmt_order : XtOrder
        QMT 原始订单对象。

    Returns
    -------
    UnifiedOrder
        统一订单对象。
    """
    # 时间戳转换为ISO格式
    create_time = datetime.fromtimestamp(qmt_order.order_time).isoformat()

    # 创建统一订单
    unified_order = UnifiedOrder.create(
        order_id=str(qmt_order.order_id),
        symbol=qmt_order.stock_code,
        direction=convert_qmt_order_type_to_direction(qmt_order.order_type).value,
        order_type=convert_qmt_price_type_to_order_type(qmt_order.price_type).value,
        volume=float(qmt_order.order_volume),
        price=float(qmt_order.price),
        status=convert_qmt_order_status_to_string(qmt_order.order_status),
        create_time=create_time,
        update_time=create_time,  # QMT没有单独的更新时间，使用创建时间
        filled_volume=float(qmt_order.traded_volume) if qmt_order.traded_volume else 0.0,
        avg_price=float(qmt_order.traded_price) if qmt_order.traded_price else 0.0,
        channel_type=TradeChannel.QMT,
    )

    # 添加 QMT 特有字段到 extra
    unified_order.extra.update(
        {
            "order_remark": qmt_order.order_remark,
            "strategy_name": qmt_order.strategy_name,
            "status_msg": qmt_order.status_msg,
            "direction": qmt_order.direction,
            "offset_flag": qmt_order.offset_flag,
            "price_type": qmt_order.price_type,
            "order_sysid": qmt_order.order_sysid,
            "secu_account": getattr(qmt_order, "secu_account", ""),
            "instrument_name": getattr(qmt_order, "instrument_name", ""),
        }
    )

    return unified_order

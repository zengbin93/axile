"""订单参数模型:渠道表达下单意图的方式.

不同渠道对同一份"调仓意图"要求不同的订单参数词汇,本模块以中性枚举
刻画这些差异,供算法层按能力分流、配置期做配对校验。

Notes
-----
模型与渠道的对应关系:

- ``POSITION_SIDE``:双向持仓语义,以 ``position_side`` 指明操作哪一侧
  持仓,并可用 ``reduce_only`` 约束纯减仓单。
- ``OFFSET``:期货开平语义,订单必须携带 ``offset_flag``
  (open/close/close_today/close_yesterday),一次订单只能有一种开平属性,
  穿零调仓须拆成"平仓腿 + 开仓腿"两笔。
- ``DIRECTIONAL``:纯方向推导,买卖方向本身即决定开平仓,无需额外参数。
- ``UNKNOWN``:渠道未声明模型。算法遇到未知模型时按"歧义即失败"处理,
  拒绝猜测下单语义。
"""

from enum import StrEnum


class OrderParamModel(StrEnum):
    """
    渠道的订单参数模型.

    Attributes
    ----------
    POSITION_SIDE : str
        双向持仓语义(position_side + reduce_only)。
    OFFSET : str
        期货开平语义(offset_flag,穿零须拆单)。
    DIRECTIONAL : str
        纯方向推导,方向即开平仓。
    UNKNOWN : str
        未声明;算法拒绝在未知模型上猜测下单语义。
    """

    POSITION_SIDE = "position_side"
    OFFSET = "offset"
    DIRECTIONAL = "directional"
    UNKNOWN = "unknown"

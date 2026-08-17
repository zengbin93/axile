"""``CtpTrader`` 拆分包.

本包替代原先的 ``axile/executor/ctp/core/trader.py``，把交易客户端按职责
拆分为多个 mixin 模块：

- :mod:`._constants`     —— 常量、数据类、异常、工具函数
- :mod:`.connection`     —— 连接 / 登录 / 重连
- :mod:`.instruments`    —— 合约查询与主力合约映射
- :mod:`.positions`      —— 持仓查询与组合拆腿
- :mod:`.orders`         —— 订单 / 成交 / 结算单 / 状态汇总
- :mod:`.risk`           —— 风控、保证金、下单前校验
- :mod:`.market_data`    —— 行情客户端代理
- :mod:`.options`        —— 期权行权 / 放弃 / 自对冲
- :mod:`._main`          —— ``CtpTrader`` 主类

外部代码继续使用 ``from axile.executor.ctp.core.trader import CtpTrader`` 即可。
为了兼容历史测试中 ``trader.<symbol>`` 风格的引用，常用类型 / 常量 / 工具函数
也在这里再导出（仅作 namespace 桥接，没有逻辑）。
"""

from axile.executor.ctp.core import openctp_compat as ctp_compat
from axile.executor.ctp.core.callback_manager import CallbackManager
from axile.executor.ctp.core.cancel_order_manager import CancelOrderManager
from axile.executor.ctp.core.objects import (
    CtpConverter,
    InstrumentField,
    OrderField,
    OrderStatusType,
    PositionField,
    TradeField,
    TradingAccountField,
)
from axile.executor.ctp.core.openctp_compat import (
    CThostFtdcTraderApi,
    THOST_FTDC_AF_Delete,
    THOST_FTDC_D_Buy,
    THOST_FTDC_D_Sell,
    THOST_FTDC_OF_Close,
    THOST_FTDC_OF_CloseToday,
    THOST_FTDC_OF_CloseYesterday,
    THOST_FTDC_OF_Open,
    THOST_FTDC_OPT_LimitPrice,
)
from axile.executor.ctp.core.trader._constants import (
    CTP_TD_GLOBAL_GROUP,
    ConnectionStatus,
    CtpCancelledError,
    CtpStateError,
    CtpTimeoutError,
    OperationCounter,
    RiskControlConfig,
    _safe_decode_content,
    _safe_release_trader_api,
    _wait_or_raise,
    get_default_clock,
)
from axile.executor.ctp.core.trader._main import CtpTrader

__all__ = [
    "CTP_TD_GLOBAL_GROUP",
    "CThostFtdcTraderApi",
    "CallbackManager",
    "CancelOrderManager",
    "ConnectionStatus",
    "CtpCancelledError",
    "CtpConverter",
    "CtpStateError",
    "CtpTimeoutError",
    "CtpTrader",
    "InstrumentField",
    "OperationCounter",
    "OrderField",
    "OrderStatusType",
    "PositionField",
    "RiskControlConfig",
    "THOST_FTDC_AF_Delete",
    "THOST_FTDC_D_Buy",
    "THOST_FTDC_D_Sell",
    "THOST_FTDC_OF_Close",
    "THOST_FTDC_OF_CloseToday",
    "THOST_FTDC_OF_CloseYesterday",
    "THOST_FTDC_OF_Open",
    "THOST_FTDC_OPT_LimitPrice",
    "TradeField",
    "TradingAccountField",
    "_safe_decode_content",
    "_safe_release_trader_api",
    "_wait_or_raise",
    "ctp_compat",
    "get_default_clock",
]

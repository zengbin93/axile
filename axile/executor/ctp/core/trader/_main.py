"""``CtpTrader`` 主类：组合所有 mixin 并集中初始化状态."""

# 主类初始化共享属性，但 mixin 方法访问时 pyright 仍可能识别不到属于
# mixin 的字段；同时 _LazySymbolProxy 让 CThostFtdcTraderApi 等类型在静态
# 分析里是 object，触发 reportInvalidTypeForm。
# pyright: reportAttributeAccessIssue=false
# pyright: reportInvalidTypeForm=false

from __future__ import annotations

import threading
from collections import deque

import loguru
import pandas as pd

from axile.executor.account_control.guard import AccountControlGuard

# 兼容外部回调框架的 callback / cancel manager 已经在外部模块定义。
from axile.executor.ctp.core.callback_manager import CallbackManager
from axile.executor.ctp.core.cancel_order_manager import CancelOrderManager
from axile.executor.ctp.core.objects import (
    InstrumentField,
    OrderField,
    PositionField,
    TradeField,
    TradingAccountField,
)
from axile.executor.ctp.core.openctp_compat import CThostFtdcTraderApi
from axile.executor.ctp.core.option_action import OptionActionTracker
from axile.executor.ctp.core.reconnect import ReconnectController, ReconnectPolicy
from axile.executor.ctp.core.trader._constants import (
    ConnectionStatus,
    RiskControlConfig,
    _safe_release_trader_api,
)
from axile.executor.ctp.core.trader.connection import ConnectionMixin
from axile.executor.ctp.core.trader.instruments import InstrumentsMixin
from axile.executor.ctp.core.trader.market_data import MarketDataMixin
from axile.executor.ctp.core.trader.options import OptionsMixin
from axile.executor.ctp.core.trader.orders import OrdersMixin
from axile.executor.ctp.core.trader.positions import PositionsMixin
from axile.executor.ctp.core.trader.risk import RiskMixin
from axile.executor.models.unified_order import UnifiedOrder


class CtpTrader(
    ConnectionMixin,
    InstrumentsMixin,
    PositionsMixin,
    OrdersMixin,
    RiskMixin,
    MarketDataMixin,
    OptionsMixin,
):
    """CTP交易客户端.

    主类只承担：

    - 在 ``__init__`` 中集中初始化所有 mixin 共享的状态字段
    - 提供 ``close`` / ``request_stop`` 等会话级生命周期方法

    各业务能力（连接、合约、持仓、订单、风控、行情、期权）由对应 mixin
    在多继承中按 MRO 顺序提供方法。**Mixin 顺序敏感**：
    ``ConnectionMixin`` 必须排在 ``OrdersMixin`` 之前，因为 ``_post_reconnect_sync``
    会调用 ``query_account/query_positions/query_orders/_query_trades_impl``。
    """

    def __init__(
        self,
        host: str,
        broker: str,
        user: str,
        password: str,
        appid: str,
        authcode: str,
        md_front: str | None = None,
        verbose: bool = False,
        logger: "loguru.Logger | None" = None,
    ) -> None:
        """
        初始化 CTP 交易客户端.

        Parameters
        ----------
        host : str
            交易前置地址。
        broker : str
            期货公司代码。
        user : str
            账户号。
        password : str
            账户密码。
        appid : str
            应用 ID。
        authcode : str
            认证码。
        md_front : str | None, optional
            行情前置地址；未提供时不自动初始化行情客户端。
        verbose : bool, default=False
            是否启用详细日志。
        logger : loguru.Logger | None, optional
            日志记录器；未提供时使用模块默认 ``loguru.logger``。
        """
        self.host = host
        self.broker = broker
        self.user = user
        self.password = password
        self.appid = appid
        self.authcode = authcode
        self.md_front = md_front
        self.verbose = verbose
        self.logger = logger or loguru.logger

        self.trading_day = ""
        self.front_id = 0
        self.session_id = 0
        self.order_ref = 0

        # 连接状态管理
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.connected = False
        self.authenticated = False
        self.logged_in = False
        self.settlement_confirmed = False

        # 自动重连配置和状态
        self.original_servers = [host]  # 保存原始服务器列表
        self.current_server_index = 0
        self.reconnect = ReconnectController(
            name="CTP",
            policy=ReconnectPolicy(
                enable_auto_reconnect=True,
                max_reconnect_attempts=10,
                reconnect_interval=5.0,
                connection_timeout=30.0,
                exponential_backoff=True,
                max_reconnect_interval=60.0,
                heartbeat_interval=30.0,
                enable_backup_servers=False,
            ),
            attempt_reconnect=self._attempt_reconnect,
            on_reconnect_success=self._post_reconnect_sync,
            logger=self.logger,
        )
        self.reconnect_config = self.reconnect.policy

        # 存储查询结果 - 使用Pydantic模型提高可读性
        self.instruments: dict[str, InstrumentField] = {}
        self.positions: dict[str, PositionField] = {}
        self.account: TradingAccountField | None = None
        self.orders: dict[str, OrderField] = {}
        self.trades: dict[str, TradeField] = {}
        self.main_contracts: dict[str, str] = {}  # 品种 -> 主力合约映射

        # 组合持仓拆腿审计映射：instrument_id -> 原始组合代码（如 "SPC a2605&m2605"）
        # 由 _save_split_leg_position 写入，data_converter 读出后填入 position.extra.combination_origin
        self.combination_origins: dict[str, str] = {}

        # 期权行权 / 放弃 / 自对冲指令的状态机维护器（独立于普通订单的 self.orders）。
        # 由 option_action() 登记，OnRspExecOrderInsert / OnErrRtnExecOrderInsert / OnRtnExecOrder 推进。
        self.option_action_tracker: OptionActionTracker = OptionActionTracker()

        # 期权合约查询批次标记：query_option_instruments() 写入 event_key，
        # OnRspQryInstrument 据此放宽期权过滤；bIsLast 时自动清理。
        self._option_query_event_keys: set[str] = set()

        # 存储统一订单模型
        self._unified_orders: dict[str, UnifiedOrder] = {}
        self._unified_orders_lock = threading.Lock()  # 保护UnifiedOrder字典的线程锁

        # 回调管理器（组合模式）
        self._callback_manager = CallbackManager(logger=self.logger)

        # 撤单状态管理器（组合模式）
        self._cancel_order_manager = CancelOrderManager(logger=self.logger)

        # 结算单内容存储
        self.settlement_content = []

        # 同步锁
        self.connect_event = threading.Event()
        self.auth_event = threading.Event()
        self.login_event = threading.Event()
        self.settlement_event = threading.Event()
        self.stop_event = threading.Event()
        self.query_events = {}
        self._account_control_guard: AccountControlGuard | None = None

        # 风控配置和数据结构
        self.risk_config = RiskControlConfig()
        self.operation_history = deque(maxlen=3000)  # 操作历史记录
        self.last_order_time = 0.0  # 最后一次报单时间
        self.risk_control_lock = threading.Lock()  # 风控操作锁

        # 行情客户端（延迟初始化）
        self.md_client = None
        self.md_connected = False

        # 创建API
        self._spi_proxy: object | None = None
        self.api: CThostFtdcTraderApi = self._create_trader_api(host)
        self._start_time = pd.to_datetime("now") - pd.Timedelta(seconds=60)

    def close(self):
        """关闭连接."""
        self.request_stop()

        # 停止自动重连
        self.stop_auto_reconnect()

        # 关闭行情客户端
        if hasattr(self, "md_client") and self.md_client:
            try:
                self.md_client.close()
                self.md_connected = False
                self.logger.info("🔌 行情客户端已关闭")
            except (AttributeError, OSError, RuntimeError):
                pass

        # 关闭交易客户端
        if hasattr(self, "api"):
            _safe_release_trader_api(self.api)
            self.api = None
            self.connected = False
            self.authenticated = False
            self.logged_in = False
            self.settlement_confirmed = False
            self.logger.info("🔌 交易客户端已关闭")

    def request_stop(self) -> None:
        """请求中止当前等待中的连接、查询和结算流程."""
        self.stop_event.set()
        self.connect_event.set()
        self.auth_event.set()
        self.login_event.set()
        self.settlement_event.set()
        for event in list(self.query_events.values()):
            event.set()

"""``CtpTrader`` 连接 / 登录 / 重连 mixin.

承载会话生命周期相关方法：建立 trader API、前置机连接、认证、登录、
结算单确认、自动重连与连接信息查询。

由 ``trader/_main.py`` 通过多继承组合到 ``CtpTrader`` 主类，所有
``self.X`` 状态由主类 ``__init__`` 初始化。
"""

# Mixin 共享属性（self.logger / self.api 等）由 _main.py 的 __init__ 初始化，
# pyright 无法静态推断；用文件级 reportAttributeAccessIssue 抑制。
# 此外 openctp_compat 的 _LazySymbolProxy 让 CThostFtdcTraderApi 等类型在静态
# 分析里是 object，触发 reportInvalidTypeForm / reportCallIssue，故一并抑制。
# pyright: reportAttributeAccessIssue=false
# pyright: reportInvalidTypeForm=false
# pyright: reportCallIssue=false

from __future__ import annotations

import os
import tempfile
from typing import Any

from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.ctp.core import openctp_compat as ctp_compat
from axile.executor.ctp.core.openctp_compat import (
    THOST_TERT_QUICK,
    CThostFtdcReqAuthenticateField,
    CThostFtdcReqUserLoginField,
    CThostFtdcSettlementInfoConfirmField,
    CThostFtdcTraderApi,
    CThostFtdcUserSystemInfoField,
)
from axile.executor.ctp.core.trader._constants import (
    ConnectionStatus,
    CtpStateError,
    _safe_release_trader_api,
    _wait_or_raise,
)

# 注：``temp_cleaner`` 必须在函数体内导入。
# ``axile.executor.ctp.utils.__init__`` 会 eager-import ``data_converter``，
# 后者反向依赖 ``CtpTrader``，从而与本模块（CtpTrader 拆分包的子模块）
# 形成循环导入。把 import 局部化是当前最稳的规避方案；要根治需要把
# ``utils/__init__`` 改为懒加载 ``data_converter``。


class ConnectionMixin:
    """连接、认证、登录与重连相关方法集合."""

    def set_account_control_guard(self, guard: AccountControlGuard | None) -> None:
        """为底层远端请求绑定账户控制 guard."""
        self._account_control_guard = guard

    def _create_trader_api(self, host: str):
        """创建交易API实例."""
        # 局部导入避开 utils.__init__ -> data_converter -> CtpTrader 的循环依赖
        from axile.executor.ctp.utils.temp_cleaner import build_ctp_flow_path, register_temp_path

        temp_dir = tempfile.gettempdir()
        flow_path = build_ctp_flow_path(temp_dir, f"{self.broker}_{self.user}", "trader")
        os.makedirs(flow_path, exist_ok=True)
        register_temp_path(flow_path)

        ctp_compat.ensure_openctp_loaded()
        api: CThostFtdcTraderApi = CThostFtdcTraderApi.CreateFtdcTraderApi(flow_path)
        self._spi_proxy = ctp_compat.create_trader_spi_proxy(self)
        api.RegisterSpi(self._spi_proxy)
        api.RegisterFront(host)
        resume_type = int(THOST_TERT_QUICK)
        api.SubscribePrivateTopic(resume_type)
        api.SubscribePublicTopic(resume_type)
        return api

    def _update_connection_status(self, status: ConnectionStatus):
        """更新连接状态."""
        old_status = self.connection_status
        self.connection_status = status
        self.logger.info(f"🔄 连接状态变更: {old_status.value} -> {status.value}")

    def _attempt_reconnect(self) -> bool:
        """尝试重连."""
        try:
            self._update_connection_status(ConnectionStatus.CONNECTING)

            # 选择服务器
            server = self._get_next_server()
            self.logger.info(f"🔄 尝试连接服务器: {server}")

            # 释放旧连接
            if hasattr(self, "api") and self.api:
                _safe_release_trader_api(self.api)

            # 创建新连接
            self.api = self._create_trader_api(server)

            # 重置事件
            self.connect_event.clear()
            self.auth_event.clear()
            self.login_event.clear()
            self.settlement_event.clear()

            # 初始化连接
            self.api.Init()

            # 等待连接完成
            _wait_or_raise(
                self.connect_event,
                self.reconnect_config.connection_timeout,
                "连接超时",
                stop_event=self.stop_event,
            )

            _wait_or_raise(
                self.auth_event,
                self.reconnect_config.connection_timeout,
                "认证超时",
                stop_event=self.stop_event,
            )

            _wait_or_raise(
                self.login_event,
                self.reconnect_config.connection_timeout,
                "登录超时",
                stop_event=self.stop_event,
            )

            _wait_or_raise(
                self.settlement_event,
                self.reconnect_config.connection_timeout,
                "结算确认超时",
                stop_event=self.stop_event,
            )

            return True

        except (ConnectionError, OSError, RuntimeError, ValueError) as e:
            self.logger.error(f"重连失败: {e}")
            return False

    def _get_next_server(self) -> str:
        """获取下一个服务器地址."""
        servers = self.original_servers.copy()

        # 如果启用了备用服务器
        if self.reconnect_config.enable_backup_servers and self.reconnect_config.backup_servers:
            servers.extend(self.reconnect_config.backup_servers)

        # 轮询选择服务器
        server = servers[self.current_server_index % len(servers)]
        self.current_server_index += 1

        return server

    def _post_reconnect_sync(self):
        """重连后的数据同步."""
        try:
            self.logger.info("🔄 开始重连后数据同步...")

            # 查询账户信息
            self.query_account()

            # 查询持仓信息
            self.query_positions()

            # 查询当日订单
            self.query_orders()

            # 查询当日成交
            self._query_trades_impl()

            self.logger.info("✅ 重连后数据同步完成")

        except (ConnectionError, OSError, RuntimeError, ValueError) as e:
            self.logger.error(f"重连后数据同步失败: {e}")

    def stop_auto_reconnect(self):
        """停止自动重连."""
        self.logger.info("🛑 停止自动重连...")
        self.reconnect.stop(timeout=5.0)

        if self.reconnect.is_running:
            self.logger.warning("⚠️  重连线程未能正常停止")
        else:
            self.logger.info("✅ 重连线程已停止")

    def update_reconnect_config(self, **kwargs: object):
        """更新重连配置."""
        changed, unknown = self.reconnect.update_policy(**kwargs)
        for key, value in changed.items():
            self.logger.info(f"✅ 重连配置已更新：{key} = {value}")
        for key in unknown:
            self.logger.warning(f"⚠️  未知的重连配置项：{key}")

    def get_connection_info(self) -> dict[str, Any]:
        """获取连接信息."""
        return {
            "connection_status": self.connection_status.value,
            "connected": self.connected,
            "authenticated": self.authenticated,
            "logged_in": self.logged_in,
            "settlement_confirmed": self.settlement_confirmed,
            "reconnect_attempts": self.reconnect.attempts,
            "last_disconnect_time": self.reconnect.last_disconnect_time,
            "auto_reconnect_enabled": self.reconnect_config.enable_auto_reconnect,
            "current_server_index": self.current_server_index,
            "available_servers": len(self.original_servers) + len(self.reconnect_config.backup_servers),
        }

    def connect(self) -> None:
        """连接CTP."""
        self.stop_event.clear()
        self.api.Init()
        _wait_or_raise(self.connect_event, 30, "连接CTP超时", stop_event=self.stop_event)

    def OnFrontConnected(self):
        """前置连接回调."""
        self.logger.info("✅ CTP前置连接成功")
        self._update_connection_status(ConnectionStatus.CONNECTED)
        self.connected = True
        self.connect_event.set()

        # 自动进行认证
        req = CThostFtdcReqAuthenticateField()
        req.BrokerID = self.broker
        req.UserID = self.user
        req.AppID = self.appid
        req.AuthCode = self.authcode
        self.api.ReqAuthenticate(req, 0)

    def OnFrontDisconnected(self, nReason):
        """前置断开回调."""
        self.logger.error(f"🔌 CTP前置连接断开: {nReason}")

        # 更新连接状态
        self._update_connection_status(ConnectionStatus.DISCONNECTED)
        self.connected = False
        self.authenticated = False
        self.logged_in = False
        self.settlement_confirmed = False
        self.reconnect.notify_disconnect()

    def OnRspAuthenticate(self, _pRspAuthenticateField, pRspInfo, _nRequestID, _bIsLast):
        """认证响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"CTP认证失败: {pRspInfo.ErrorMsg}")
            self.auth_event.set()
            return

        self.logger.info("✅ CTP认证成功")
        self._update_connection_status(ConnectionStatus.AUTHENTICATED)
        self.authenticated = True
        self.auth_event.set()

        # 注册客户端系统信息
        system_info = CThostFtdcUserSystemInfoField()
        system_info.BrokerID = self.broker
        system_info.UserID = self.user
        # 系统信息长度和内容（可以为空）
        system_info.ClientAppID = self.appid
        system_info.ClientSystemInfo = self.appid
        system_info.ClientSystemInfoLen = len(system_info.ClientSystemInfo)
        system_info.ClientPublicIP = ""
        system_info.ClientLoginRemark = "axile"
        self.api.RegisterUserSystemInfo(system_info)

        # 自动登录
        req = CThostFtdcReqUserLoginField()
        req.BrokerID = self.broker
        req.UserID = self.user
        req.Password = self.password
        req.UserProductInfo = "ctp"
        # OpenCTP API 兼容不同版本：有些版本需显式传入 `is_last` 与 `user_product_info`。
        try:
            self.api.ReqUserLogin(req, 0, False, req.UserProductInfo)
        except TypeError:
            self.api.ReqUserLogin(req, 0)

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, _nRequestID, _bIsLast):
        """登录响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"CTP登录失败: {pRspInfo.ErrorMsg}")
            self.login_event.set()
            return

        self.logger.info(f"✅ CTP登录成功: {pRspUserLogin.TradingDay}")
        self._update_connection_status(ConnectionStatus.LOGGED_IN)
        self.logged_in = True
        self.trading_day = pRspUserLogin.TradingDay
        self.front_id = pRspUserLogin.FrontID
        self.session_id = pRspUserLogin.SessionID
        self.order_ref = int(pRspUserLogin.MaxOrderRef) + 1
        self.login_event.set()

    def login(self) -> None:
        """登录CTP."""
        _wait_or_raise(self.auth_event, 30, "CTP认证超时", stop_event=self.stop_event)
        if not self.authenticated:
            raise CtpStateError("CTP认证失败")

        _wait_or_raise(self.login_event, 30, "CTP登录超时", stop_event=self.stop_event)
        if not self.logged_in:
            raise CtpStateError("CTP登录失败")

        # 自动确认结算单
        self.confirm_settlement()

    def confirm_settlement(self) -> None:
        """确认结算单 - 先查询详情再确认."""
        # 先查询结算单详情
        self.logger.info("📋 开始查询结算单详情...")
        settlement_info = self.query_settlement_info()

        # 展示结算单详情
        if settlement_info:
            self.logger.info("✅ 查询到结算单详情，准备确认")
        else:
            self.logger.warning("⚠️  未查询到结算单详情，继续确认流程")

        # 确认结算单
        self.logger.info("✅ 开始确认结算单...")
        req = CThostFtdcSettlementInfoConfirmField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        self.api.ReqSettlementInfoConfirm(req, 0)

        _wait_or_raise(self.settlement_event, 30, "确认结算单超时", stop_event=self.stop_event)
        if not self.settlement_confirmed:
            raise CtpStateError("确认结算单失败")

    def OnRspSettlementInfoConfirm(self, _pSettlementInfoConfirm, pRspInfo, _nRequestID, _bIsLast):
        """确认结算单响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"确认结算单失败: {pRspInfo.ErrorMsg}")
            self.settlement_event.set()
            return

        self.logger.info("✅ 确认结算单成功")
        self._update_connection_status(ConnectionStatus.READY)
        self.settlement_confirmed = True
        self.settlement_event.set()

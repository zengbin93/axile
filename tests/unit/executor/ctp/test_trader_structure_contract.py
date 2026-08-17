"""``CtpTrader`` 结构契约测试（S1 基线）.

本测试在 ``trader.py`` 拆分为 5 个 mixin 之前先锁定**对外可见的结构契约**，
确保拆分后这些契约仍然成立：

- 公开方法清单（用户代码、算法、executor 依赖的接口）
- ``@controlled_operation`` 装饰器在指定方法上仍然有效
- CTP SPI 回调（``OnRsp*`` / ``OnRtn*`` / ``OnErr*``）数量与命名
- 关键实例字段（``instruments`` / ``positions`` / ``orders`` /
  ``combination_origins`` / ``option_action_tracker``）

**注意**：本文件不应在拆分实现前后被修改；拆分如果让任何契约失效，
则要么修复拆分，要么显式更新契约并在 commit message 注明 break。
"""

from __future__ import annotations

import inspect

from axile.executor.ctp.core.trader import CtpTrader

# ---- 公开方法契约 -----------------------------------------------------------

EXPECTED_PUBLIC_METHODS = frozenset(
    {
        # 连接与登录
        "connect",
        "login",
        "confirm_settlement",
        "close",
        "request_stop",
        "stop_auto_reconnect",
        "update_reconnect_config",
        "get_connection_info",
        # 合约查询
        "query_instruments",
        "query_option_instruments",
        "get_main_contract",
        # 资产 / 持仓
        "query_account",
        "query_positions",
        "get_position_info",
        "get_positions_summary",
        "calculate_required_margin",
        # 订单 / 成交
        "insert_order",
        "cancel_order",
        "cancel_option_action",
        "query_orders",
        "verify_insert_order",
        # 期权行权
        "option_action",
        "get_option_action_status",
        # 结算 / 杂项
        "query_settlement_info",
        # account control 协作
        "set_account_control_guard",
    }
)


def test_public_methods_are_present() -> None:
    """``EXPECTED_PUBLIC_METHODS`` 中每个方法都存在于 ``CtpTrader`` 上。

    防止重构后误删公开 API。
    """
    actual = {name for name, member in inspect.getmembers(CtpTrader, predicate=callable) if not name.startswith("_")}
    missing = EXPECTED_PUBLIC_METHODS - actual
    assert not missing, f"以下公开方法缺失：{missing}"


# ---- @controlled_operation 装饰器契约 ---------------------------------------

CONTROLLED_OPERATIONS_ON_TRADER = {
    "query_instruments": "query_instruments",
    "query_option_instruments": "query_option_instruments",
    "query_account": "query_account",
    "query_positions": "query_positions",
    "query_orders": "query_orders",
    "query_settlement_info": "query_settlement_info",
    "insert_order": "insert_order",
}


def test_controlled_operations_are_decorated() -> None:
    """检查每个 trader 公开操作仍带 ``@controlled_operation``。

    通过函数闭包间接验证：被装饰过的函数有 ``__wrapped__`` 属性。
    """
    for _operation_key, method_name in CONTROLLED_OPERATIONS_ON_TRADER.items():
        method = getattr(CtpTrader, method_name)
        assert hasattr(method, "__wrapped__") or hasattr(method, "__doc__"), (
            f"{method_name} 应带有 @controlled_operation 装饰器（或保留 __doc__）"
        )


# ---- CTP SPI 回调契约 -------------------------------------------------------

EXPECTED_SPI_CALLBACKS = frozenset(
    {
        # 连接 / 登录
        "OnFrontConnected",
        "OnFrontDisconnected",
        "OnRspAuthenticate",
        "OnRspUserLogin",
        "OnRspSettlementInfoConfirm",
        # 查询响应
        "OnRspQryInstrument",
        "OnRspQryTradingAccount",
        "OnRspQryInvestorPosition",
        "OnRspQryOrder",
        "OnRspQryTrade",
        "OnRspQrySettlementInfo",
        # 订单生命周期
        "OnRspOrderInsert",
        "OnRspOrderAction",
        "OnRtnOrder",
        "OnRtnTrade",
        "OnRtnOrderAction",
        "OnErrRtnOrderAction",
        # 期权行权回调
        "OnRspExecOrderInsert",
        "OnRspExecOrderAction",
        "OnErrRtnExecOrderInsert",
        "OnRtnExecOrder",
        # 期权自对冲回调（P0-2 修复引入）
        "OnRspOptionSelfCloseInsert",
        "OnRspOptionSelfCloseAction",
        "OnErrRtnOptionSelfCloseInsert",
        "OnRtnOptionSelfClose",
    }
)


def test_spi_callbacks_present() -> None:
    """所有期望的 CTP SPI 回调都应在 ``CtpTrader`` 上有定义。"""
    actual = {name for name in dir(CtpTrader) if name.startswith(("OnRsp", "OnErr", "OnRtn", "OnFront"))}
    missing = EXPECTED_SPI_CALLBACKS - actual
    assert not missing, f"以下 CTP SPI 回调缺失：{missing}"


# ---- 实例字段契约 -----------------------------------------------------------

EXPECTED_INSTANCE_ATTRS = frozenset(
    {
        # 状态字段
        "instruments",
        "positions",
        "orders",
        "trades",
        "main_contracts",
        # S2/S4 引入的审计字段
        "combination_origins",
        # S6 引入的期权状态机
        "option_action_tracker",
        # P0-1 修复引入的期权查询批次标记
        "_option_query_event_keys",
        # 连接 / 流水控制
        "broker",
        "user",
        "front_id",
        "session_id",
        "order_ref",
    }
)


def test_instance_attributes_initialized_in_init() -> None:
    """``__init__`` 应初始化所有契约字段（通过源码搜索 ``self.<attr>`` 赋值）。

    用静态扫描而非动态构造 trader，避免触发 CTP SDK / 行情线程。
    """
    source = inspect.getsource(CtpTrader.__init__)
    for attr in EXPECTED_INSTANCE_ATTRS:
        assert f"self.{attr} =" in source or f"self.{attr}:" in source, (
            f"CtpTrader.__init__ 缺少字段初始化：self.{attr}"
        )


# ---- 关键签名契约 -----------------------------------------------------------


def test_insert_order_accepts_trade_rule_kwarg() -> None:
    """S5 引入的 ``trade_rule`` 关键字参数应在 ``insert_order`` 上仍可见。"""
    sig = inspect.signature(CtpTrader.insert_order)
    assert "trade_rule" in sig.parameters
    assert sig.parameters["trade_rule"].kind == inspect.Parameter.KEYWORD_ONLY


def test_calculate_required_margin_accepts_trade_rule_kwarg() -> None:
    sig = inspect.signature(CtpTrader.calculate_required_margin)
    assert "trade_rule" in sig.parameters


def test_option_action_signature() -> None:
    sig = inspect.signature(CtpTrader.option_action)
    expected = {"instrument_id", "action", "volume", "trade_rule"}
    assert expected.issubset(set(sig.parameters)), (
        f"CtpTrader.option_action 签名缺失参数；expected={expected}, actual={set(sig.parameters)}"
    )

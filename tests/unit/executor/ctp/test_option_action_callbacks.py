"""``CtpTrader`` 期权行权回调路由单测.

聚焦 ``OnRspExecOrderInsert`` / ``OnErrRtnExecOrderInsert`` /
``OnRtnExecOrder`` / ``OnRspExecOrderAction`` 四个回调对状态机的推进，
通过最小 trader stub 直接测试回调函数，避免触发 CTP API 实际调用。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from axile.executor.ctp.core.option_action import (
    OptionActionStatus,
    OptionActionTracker,
    OptionActionType,
)
from axile.executor.ctp.core.trader import CtpTrader


@pytest.fixture
def trader_with_pending() -> CtpTrader:
    """构造 trader 桩件，已登记 1 条 Pending 行权指令。"""
    trader = CtpTrader.__new__(CtpTrader)
    trader.option_action_tracker = OptionActionTracker()
    trader.logger = MagicMock()
    trader.option_action_tracker.register(
        order_ref="42",
        instrument_id="m2510-C-3100",
        action=OptionActionType.EXERCISE,
        volume=5,
    )
    return trader


def _input_exec(order_ref: str = "42"):
    return SimpleNamespace(ExecOrderRef=order_ref)


def _rsp_info(error_id: int = 0, msg: str = ""):
    return SimpleNamespace(ErrorID=error_id, ErrorMsg=msg)


class TestOnRspExecOrderInsert:
    def test_no_error_promotes_to_submitted(self, trader_with_pending: CtpTrader) -> None:
        trader_with_pending.OnRspExecOrderInsert(_input_exec(), _rsp_info(0), 1, True)
        assert trader_with_pending.option_action_tracker.get("42").status == OptionActionStatus.SUBMITTED

    def test_error_marks_failed_with_front_source(self, trader_with_pending: CtpTrader) -> None:
        trader_with_pending.OnRspExecOrderInsert(_input_exec(), _rsp_info(999, "前置机拒绝"), 1, True)
        record = trader_with_pending.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_id == 999
        assert record.error_source == "front"

    def test_missing_order_ref_no_op(self, trader_with_pending: CtpTrader) -> None:
        trader_with_pending.OnRspExecOrderInsert(_input_exec(""), _rsp_info(), 1, True)
        # 不应改动现有 record
        assert trader_with_pending.option_action_tracker.get("42").status == OptionActionStatus.PENDING


class TestOnErrRtnExecOrderInsert:
    def test_exchange_reject_marks_failed(self, trader_with_pending: CtpTrader) -> None:
        trader_with_pending.OnErrRtnExecOrderInsert(_input_exec(), _rsp_info(2000, "交易所拒绝"))
        record = trader_with_pending.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_source == "exchange"
        assert record.error_id == 2000

    def test_pending_to_failed_via_exchange(self, trader_with_pending: CtpTrader) -> None:
        # 即使在 Pending 阶段也允许直接被交易所拒绝（少见但合法）
        trader_with_pending.OnErrRtnExecOrderInsert(_input_exec(), _rsp_info(3000, "限制"))
        assert trader_with_pending.option_action_tracker.get("42").status == OptionActionStatus.FAILED


class TestOnRtnExecOrder:
    @pytest.fixture
    def trader_after_submitted(self, trader_with_pending: CtpTrader) -> CtpTrader:
        trader_with_pending.option_action_tracker.transition("42", OptionActionStatus.SUBMITTED)
        return trader_with_pending

    def test_exec_result_executed(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnExecOrder(SimpleNamespace(ExecOrderRef="42", ExecResult="3"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.EXECUTED

    def test_exec_result_abandoned(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnExecOrder(SimpleNamespace(ExecOrderRef="42", ExecResult="5"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.ABANDONED

    def test_exec_result_cancelled_user(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnExecOrder(SimpleNamespace(ExecOrderRef="42", ExecResult="1"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.CANCELLED

    def test_exec_result_cancelled_auto(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnExecOrder(SimpleNamespace(ExecOrderRef="42", ExecResult="2"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.CANCELLED

    def test_exec_result_rejected(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnExecOrder(
            SimpleNamespace(ExecOrderRef="42", ExecResult="4", StatusMsg="rejected", ErrorID=10)
        )
        record = trader_after_submitted.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_id == 10

    def test_exec_result_sent_is_intermediate(self, trader_after_submitted: CtpTrader) -> None:
        # ExecResult="0" 是中间态，不应改变状态机
        trader_after_submitted.OnRtnExecOrder(SimpleNamespace(ExecOrderRef="42", ExecResult="0"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.SUBMITTED

    def test_unknown_exec_result_warns_and_no_op(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnExecOrder(SimpleNamespace(ExecOrderRef="42", ExecResult="X"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.SUBMITTED
        assert trader_after_submitted.logger.warning.called


class TestOnRspExecOrderAction:
    def test_action_error_falls_back_to_failed(self, trader_with_pending: CtpTrader) -> None:
        trader_with_pending.option_action_tracker.transition("42", OptionActionStatus.SUBMITTED)
        trader_with_pending.option_action_tracker.transition("42", OptionActionStatus.CANCELLING)

        trader_with_pending.OnRspExecOrderAction(_input_exec(), _rsp_info(500, "撤销失败"), 1, True)

        record = trader_with_pending.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_source == "front"

    def test_action_no_error_keeps_state(self, trader_with_pending: CtpTrader) -> None:
        trader_with_pending.option_action_tracker.transition("42", OptionActionStatus.SUBMITTED)
        trader_with_pending.option_action_tracker.transition("42", OptionActionStatus.CANCELLING)

        # 无错误响应时不应推进状态；等 OnRtnExecOrder 推到 Cancelled
        trader_with_pending.OnRspExecOrderAction(_input_exec(), _rsp_info(0), 1, True)
        assert trader_with_pending.option_action_tracker.get("42").status == OptionActionStatus.CANCELLING


# ---- P0-2：SelfClose 4 个 SPI 回调单测 ----------------------------------------


def _input_self_close(order_ref: str = "42"):
    """SelfClose 协议使用 OptionSelfCloseRef 字段（与 ExecOrderRef 不同）。"""
    return SimpleNamespace(OptionSelfCloseRef=order_ref)


@pytest.fixture
def trader_with_self_close_pending() -> CtpTrader:
    """构造 trader 桩件，已登记 1 条 Pending 自对冲指令。"""
    trader = CtpTrader.__new__(CtpTrader)
    trader.option_action_tracker = OptionActionTracker()
    trader.logger = MagicMock()
    trader.option_action_tracker.register(
        order_ref="42",
        instrument_id="m2510-C-3100",
        action=OptionActionType.SELF_CLOSE,
        volume=5,
    )
    return trader


class TestOnRspOptionSelfCloseInsert:
    def test_no_error_promotes_to_submitted(self, trader_with_self_close_pending: CtpTrader) -> None:
        trader_with_self_close_pending.OnRspOptionSelfCloseInsert(_input_self_close(), _rsp_info(0), 1, True)
        assert trader_with_self_close_pending.option_action_tracker.get("42").status == OptionActionStatus.SUBMITTED

    def test_error_marks_failed_with_front_source(self, trader_with_self_close_pending: CtpTrader) -> None:
        trader_with_self_close_pending.OnRspOptionSelfCloseInsert(
            _input_self_close(), _rsp_info(999, "前置机拒绝"), 1, True
        )
        record = trader_with_self_close_pending.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_id == 999
        assert record.error_source == "front"

    def test_missing_order_ref_no_op(self, trader_with_self_close_pending: CtpTrader) -> None:
        trader_with_self_close_pending.OnRspOptionSelfCloseInsert(_input_self_close(""), _rsp_info(), 1, True)
        assert trader_with_self_close_pending.option_action_tracker.get("42").status == OptionActionStatus.PENDING


class TestOnErrRtnOptionSelfCloseInsert:
    def test_exchange_reject_marks_failed(self, trader_with_self_close_pending: CtpTrader) -> None:
        trader_with_self_close_pending.OnErrRtnOptionSelfCloseInsert(_input_self_close(), _rsp_info(2000, "交易所拒绝"))
        record = trader_with_self_close_pending.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_source == "exchange"
        assert record.error_id == 2000


class TestOnRtnOptionSelfClose:
    @pytest.fixture
    def trader_after_submitted(self, trader_with_self_close_pending: CtpTrader) -> CtpTrader:
        trader_with_self_close_pending.option_action_tracker.transition("42", OptionActionStatus.SUBMITTED)
        return trader_with_self_close_pending

    def test_exec_result_executed(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnOptionSelfClose(SimpleNamespace(OptionSelfCloseRef="42", ExecResult="3"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.EXECUTED

    def test_exec_result_cancelled_user(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnOptionSelfClose(SimpleNamespace(OptionSelfCloseRef="42", ExecResult="1"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.CANCELLED

    def test_exec_result_cancelled_auto(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnOptionSelfClose(SimpleNamespace(OptionSelfCloseRef="42", ExecResult="2"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.CANCELLED

    def test_exec_result_rejected(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnOptionSelfClose(
            SimpleNamespace(OptionSelfCloseRef="42", ExecResult="4", StatusMsg="rejected", ErrorID=10)
        )
        record = trader_after_submitted.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_id == 10

    def test_exec_result_sent_is_intermediate(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnOptionSelfClose(SimpleNamespace(OptionSelfCloseRef="42", ExecResult="0"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.SUBMITTED

    def test_unknown_exec_result_warns_and_no_op(self, trader_after_submitted: CtpTrader) -> None:
        trader_after_submitted.OnRtnOptionSelfClose(SimpleNamespace(OptionSelfCloseRef="42", ExecResult="X"))
        assert trader_after_submitted.option_action_tracker.get("42").status == OptionActionStatus.SUBMITTED
        assert trader_after_submitted.logger.warning.called


class TestOnRspOptionSelfCloseAction:
    def test_action_error_falls_back_to_failed(self, trader_with_self_close_pending: CtpTrader) -> None:
        trader_with_self_close_pending.option_action_tracker.transition("42", OptionActionStatus.SUBMITTED)
        trader_with_self_close_pending.option_action_tracker.transition("42", OptionActionStatus.CANCELLING)

        trader_with_self_close_pending.OnRspOptionSelfCloseAction(
            _input_self_close(), _rsp_info(500, "撤销失败"), 1, True
        )

        record = trader_with_self_close_pending.option_action_tracker.get("42")
        assert record.status == OptionActionStatus.FAILED
        assert record.error_source == "front"

    def test_action_no_error_keeps_state(self, trader_with_self_close_pending: CtpTrader) -> None:
        trader_with_self_close_pending.option_action_tracker.transition("42", OptionActionStatus.SUBMITTED)
        trader_with_self_close_pending.option_action_tracker.transition("42", OptionActionStatus.CANCELLING)

        trader_with_self_close_pending.OnRspOptionSelfCloseAction(_input_self_close(), _rsp_info(0), 1, True)
        assert trader_with_self_close_pending.option_action_tracker.get("42").status == OptionActionStatus.CANCELLING


# ---- P0-2：_build_option_self_close_request 字段类型校验 ----------------------


def test_build_option_self_close_request_uses_self_close_field_type() -> None:
    """SelfClose 请求必须用 CThostFtdcInputOptionSelfCloseField，并设置 OptionSelfCloseRef。"""
    from axile.executor.ctp.core.openctp_compat import (
        CThostFtdcInputOptionSelfCloseField,
        THOST_FTDC_HF_Speculation,
        THOST_FTDC_OCF_CloseSelfOptionPosition,
    )

    trader = CtpTrader.__new__(CtpTrader)
    trader.broker = "9999"
    trader.user = "000001"

    req = trader._build_option_self_close_request("m2510-C-3100", "42", 5)

    # 确认请求对象是 SelfClose 专用结构体的实例（lazy proxy 也认可）
    assert isinstance(req, CThostFtdcInputOptionSelfCloseField) or req.__class__.__name__ in (
        "CThostFtdcInputOptionSelfCloseField",
        "_PlaceholderStruct",
    )
    # 关键字段：流水号字段名是 OptionSelfCloseRef，不是 ExecOrderRef
    assert req.OptionSelfCloseRef == "42"
    assert req.InstrumentID == "m2510-C-3100"
    assert req.Volume == 5
    assert req.HedgeFlag == THOST_FTDC_HF_Speculation
    assert req.OptSelfCloseFlag == THOST_FTDC_OCF_CloseSelfOptionPosition

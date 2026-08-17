"""``CtpTrader`` 期权行权 / 放弃 / 自对冲 mixin.

封装 ``ReqExecOrderInsert`` / ``ReqExecOrderAction`` /
``ReqOptionSelfCloseInsert`` 三类请求与对应回报，并通过独立的
``OptionActionTracker`` 状态机推进。
"""

# Mixin 共享属性（self.logger / self.api / self.broker 等）由 _main.py 的
# __init__ 初始化，pyright 无法静态推断；用文件级 reportAttributeAccessIssue
# 抑制。
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from axile.executor.account_control.decorator_registry import (
    build_registered_operation,
    register_operation_bootstrap,
    register_or_validate_operation,
)
from axile.executor.account_control.decorators import run_controlled_call
from axile.executor.account_control.registry import register_default_registry_bootstrap
from axile.executor.ctp.core.openctp_compat import (
    CThostFtdcInputExecOrderActionField,
    CThostFtdcInputExecOrderField,
    CThostFtdcInputOptionSelfCloseActionField,
    CThostFtdcInputOptionSelfCloseField,
    THOST_FTDC_AF_Delete,
    THOST_FTDC_AT_Abandon,
    THOST_FTDC_AT_Execute,
    THOST_FTDC_D_Buy,
    THOST_FTDC_HF_Speculation,
    THOST_FTDC_OCF_CloseSelfOptionPosition,
    THOST_FTDC_OCF_ReserveOptionPosition,
)
from axile.executor.ctp.core.option_action import (
    OPTION_ERROR_SOURCE_EXCHANGE,
    OPTION_ERROR_SOURCE_FRONT,
    OptionActionRecord,
    OptionActionStatus,
    OptionActionType,
)
from axile.executor.ctp.core.option_action import operation_key as option_operation_key
from axile.executor.ctp.core.trader._constants import CTP_TD_GLOBAL_GROUP


# 期权行权使用 ``run_controlled_call`` 在运行期按 action 选 operation key，
# 没有静态 ``@controlled_operation`` 装饰器；这里在模块加载时显式注册
# 三个 operation key 与对应的限流组，以便 preset 引用时不会报"未注册"。
def _register_option_operations() -> None:
    for op_key in ("option_exercise", "option_abandon", "option_self_close"):
        operation = build_registered_operation(op_key, groups=(CTP_TD_GLOBAL_GROUP,))
        register_or_validate_operation(operation)
        register_default_registry_bootstrap(lambda op=operation: register_operation_bootstrap(op))


_register_option_operations()


class OptionsMixin:
    """期权行权 / 放弃 / 自对冲与对应回调路由。"""

    def option_action(
        self,
        *,
        instrument_id: str,
        action: OptionActionType,
        volume: int,
        trade_rule: dict[str, object] | None = None,
    ) -> str:
        """
        提交期权行权 / 放弃 / 自对冲指令.

        Parameters
        ----------
        instrument_id : str
            期权合约代码（如 ``"m2510-C-3100"``）。
        action : OptionActionType
            指令类型 ``EXERCISE`` / ``ABANDON`` / ``SELF_CLOSE``。
        volume : int
            张数。必须为正整数。
        trade_rule : dict[str, object] | None, optional
            交易规则；预留字段，本期不参与计算。

        Returns
        -------
        str
            CTP 流水号 ``order_ref``，可作为后续 ``cancel_option_action``
            或 ``option_action_tracker.get(...)`` 的 key。

        Raises
        ------
        ValueError
            volume 非正整数，或合约不存在 / 不是期权。
        """
        del trade_rule  # 预留参数；当前公式无依赖

        if volume <= 0:
            raise ValueError(f"option_action 张数必须为正：{volume}")

        instrument = self.instruments.get(instrument_id)
        if instrument is None:
            raise ValueError(f"未找到期权合约 {instrument_id}，请先 query_instruments")
        if instrument.ProductClass != "2":
            raise ValueError(f"合约 {instrument_id} 不是期权（ProductClass={instrument.ProductClass}）")

        operation = option_operation_key(action)
        order_ref_int = self.order_ref
        self.order_ref += 1
        order_ref_str = str(order_ref_int)

        # 把行权登记 + ReqExecOrderInsert / ReqOptionSelfCloseInsert 调用都包在 guard 内，
        # 让账户控制限流可以阻止短时间内的批量行权风暴。
        def _do_submit() -> str:
            self.option_action_tracker.register(
                order_ref=order_ref_str,
                instrument_id=instrument_id,
                action=action,
                volume=int(volume),
            )

            if action == OptionActionType.SELF_CLOSE:
                req = self._build_option_self_close_request(instrument_id, order_ref_str, int(volume))
                ret = self.api.ReqOptionSelfCloseInsert(req, 0)
            else:
                req = self._build_exec_order_request(instrument_id, action, order_ref_str, int(volume))
                ret = self.api.ReqExecOrderInsert(req, 0)

            self.logger.warning(
                f"📤 提交期权指令: {instrument_id} action={action.value} 张数={volume} (ref={order_ref_str}, ret={ret})"
            )
            return order_ref_str

        return run_controlled_call(
            guard=self._account_control_guard,
            operation=operation,
            symbol=instrument_id,
            metadata={"action": action.value, "volume": int(volume), "order_ref": order_ref_str},
            call=_do_submit,
            success_outcome="submitted",
        )

    def cancel_option_action(self, order_ref: str) -> bool:
        """
        撤销已提交但尚未受理的期权行权 / 放弃 / 自对冲指令.

        Parameters
        ----------
        order_ref : str
            ``option_action()`` 返回的流水号。

        Returns
        -------
        bool
            撤销请求是否发送成功。

        Notes
        -----
        - 行权 / 放弃：调用 ``ReqExecOrderAction``，对应回报
          ``OnRspExecOrderAction``。
        - 自对冲：调用 ``ReqOptionSelfCloseAction``，对应回报
          ``OnRspOptionSelfCloseAction``。
        - 状态机变更为 ``Submitted → Cancelling``，最终态由对应回调推进。
        """
        record = self.option_action_tracker.get(order_ref)
        if record is None:
            self.logger.error(f"❌ 期权指令撤销失败：order_ref={order_ref} 不存在")
            return False
        if record.status != OptionActionStatus.SUBMITTED:
            self.logger.warning(f"⚠️ 期权指令 {order_ref} 当前状态 {record.status.value}，不在 SUBMITTED 状态，无法撤销")
            return False

        if record.action == OptionActionType.SELF_CLOSE:
            req = CThostFtdcInputOptionSelfCloseActionField()
            req.BrokerID = self.broker
            req.InvestorID = self.user
            req.UserID = self.user
            req.OptionSelfCloseRef = order_ref
            req.FrontID = self.front_id
            req.SessionID = self.session_id
            req.InstrumentID = record.instrument_id
            req.ActionFlag = THOST_FTDC_AF_Delete
            ret = self.api.ReqOptionSelfCloseAction(req, 0)
        else:
            req = CThostFtdcInputExecOrderActionField()
            req.BrokerID = self.broker
            req.InvestorID = self.user
            req.UserID = self.user
            req.ExecOrderRef = order_ref
            req.FrontID = self.front_id
            req.SessionID = self.session_id
            req.InstrumentID = record.instrument_id
            req.ActionFlag = THOST_FTDC_AF_Delete
            ret = self.api.ReqExecOrderAction(req, 0)

        if ret == 0:
            self.option_action_tracker.transition(order_ref, OptionActionStatus.CANCELLING)
            self.logger.info(f"📤 期权撤销请求已发送: ref={order_ref} action={record.action.value} ret=0")
            return True

        self.logger.error(f"❌ 期权撤销请求发送失败: ref={order_ref} ret={ret}")
        return False

    def get_option_action_status(self, order_ref: str) -> OptionActionRecord | None:
        """读取期权指令当前状态机快照."""
        return self.option_action_tracker.get(order_ref)

    def _build_exec_order_request(
        self,
        instrument_id: str,
        action: OptionActionType,
        order_ref: str,
        volume: int,
    ):
        """构造 ``CThostFtdcInputExecOrderField`` 请求对象。"""
        req = CThostFtdcInputExecOrderField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        req.UserID = self.user
        req.InstrumentID = instrument_id
        req.ExecOrderRef = order_ref
        req.Volume = volume
        req.HedgeFlag = THOST_FTDC_HF_Speculation
        req.ActionType = THOST_FTDC_AT_Execute if action == OptionActionType.EXERCISE else THOST_FTDC_AT_Abandon
        # 行权 / 放弃指令默认不平自有期权头寸；自对冲走另一条 API
        req.PosiDirection = THOST_FTDC_D_Buy
        req.ReservePositionFlag = THOST_FTDC_OCF_ReserveOptionPosition
        req.CloseFlag = THOST_FTDC_OCF_CloseSelfOptionPosition if action == OptionActionType.EXERCISE else "0"
        return req

    def _build_option_self_close_request(self, instrument_id: str, order_ref: str, volume: int):
        """构造 ``CThostFtdcInputOptionSelfCloseField`` 请求对象。

        Notes
        -----
        SelfClose 结构体的流水号字段是 ``OptionSelfCloseRef``（与 ExecOrder
        的 ``ExecOrderRef`` 不同）；下游回调 ``OnRtnOptionSelfClose`` 等也
        通过 ``OptionSelfCloseRef`` 提取 ref。
        """
        req = CThostFtdcInputOptionSelfCloseField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        req.UserID = self.user
        req.InstrumentID = instrument_id
        req.OptionSelfCloseRef = order_ref
        req.Volume = volume
        req.HedgeFlag = THOST_FTDC_HF_Speculation
        req.OptSelfCloseFlag = THOST_FTDC_OCF_CloseSelfOptionPosition
        return req

    # ----- 期权行权回调 -----

    def OnRspExecOrderInsert(self, _pInputExecOrder, pRspInfo, _nRequestID, _bIsLast):
        """前置机对行权指令的同步应答；带错误码即视为 Failed."""
        order_ref = str(getattr(_pInputExecOrder, "ExecOrderRef", "") or "")
        if not order_ref:
            return

        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"❌ 期权指令前置机拒绝: ref={order_ref} 错误={pRspInfo.ErrorMsg}")
            try:
                self.option_action_tracker.transition(
                    order_ref,
                    OptionActionStatus.FAILED,
                    error_id=int(pRspInfo.ErrorID),
                    error_msg=str(pRspInfo.ErrorMsg),
                    error_source=OPTION_ERROR_SOURCE_FRONT,
                )
            except (KeyError, ValueError) as exc:
                self.logger.warning(f"行权状态机转移失败: {exc}")
            return

        # 无错误：等同于 Pending → Submitted
        try:
            self.option_action_tracker.transition(order_ref, OptionActionStatus.SUBMITTED)
        except (KeyError, ValueError) as exc:
            self.logger.warning(f"行权状态机转移失败: {exc}")

    def OnErrRtnExecOrderInsert(self, _pInputExecOrder, pRspInfo):
        """交易所对行权指令的异步拒绝；映射为 Failed 终态。"""
        order_ref = str(getattr(_pInputExecOrder, "ExecOrderRef", "") or "")
        if not order_ref:
            return

        error_id = int(getattr(pRspInfo, "ErrorID", 0) or 0)
        error_msg = str(getattr(pRspInfo, "ErrorMsg", "") or "")
        self.logger.error(f"❌ 期权指令交易所拒绝: ref={order_ref} 错误={error_msg}")
        try:
            self.option_action_tracker.transition(
                order_ref,
                OptionActionStatus.FAILED,
                error_id=error_id,
                error_msg=error_msg,
                error_source=OPTION_ERROR_SOURCE_EXCHANGE,
            )
        except (KeyError, ValueError) as exc:
            self.logger.warning(f"行权状态机转移失败: {exc}")

    def OnRtnExecOrder(self, pExecOrder):
        """行权指令的状态推送；按 ExecResult 推进至 Executed/Abandoned/Cancelled。"""
        order_ref = str(getattr(pExecOrder, "ExecOrderRef", "") or "")
        if not order_ref:
            return

        # CTP ExecResult 取值：'0' 已发送 / '1' 已撤销 / '2' 自动撤销 / '3' 已经执行 / '4' 拒绝 / '5' 已经放弃
        # 我们按终态进行映射。
        exec_result = str(getattr(pExecOrder, "ExecResult", "") or "")
        target_status: OptionActionStatus | None = None
        if exec_result == "3":
            target_status = OptionActionStatus.EXECUTED
        elif exec_result == "5":
            target_status = OptionActionStatus.ABANDONED
        elif exec_result in ("1", "2"):
            target_status = OptionActionStatus.CANCELLED
        elif exec_result == "4":
            target_status = OptionActionStatus.FAILED
        elif exec_result == "0":
            # "已发送"是中间态；不强制转移以避免幂等问题
            return
        else:
            self.logger.warning(f"OnRtnExecOrder 未知 ExecResult={exec_result} ref={order_ref}")
            return

        try:
            self.option_action_tracker.transition(
                order_ref,
                target_status,
                error_id=int(getattr(pExecOrder, "ErrorID", 0) or 0)
                if target_status == OptionActionStatus.FAILED
                else 0,
                error_msg=str(getattr(pExecOrder, "StatusMsg", "") or ""),
            )
        except (KeyError, ValueError) as exc:
            self.logger.warning(f"行权状态机推进失败: ref={order_ref} 目标={target_status} 异常={exc}")

    def OnRspExecOrderAction(self, _pInputExecOrderAction, pRspInfo, _nRequestID, _bIsLast):
        """期权撤销请求的应答；错误时回退到 Failed，否则等待 OnRtnExecOrder。"""
        order_ref = str(getattr(_pInputExecOrderAction, "ExecOrderRef", "") or "")
        if not order_ref:
            return

        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"❌ 期权撤销失败: ref={order_ref} 错误={pRspInfo.ErrorMsg}")
            try:
                self.option_action_tracker.transition(
                    order_ref,
                    OptionActionStatus.FAILED,
                    error_id=int(pRspInfo.ErrorID),
                    error_msg=str(pRspInfo.ErrorMsg),
                    error_source=OPTION_ERROR_SOURCE_FRONT,
                )
            except (KeyError, ValueError) as exc:
                self.logger.warning(f"行权撤销状态机转移失败: {exc}")

    # ----- 期权自对冲（OptionSelfClose）回调 -----

    def OnRspOptionSelfCloseInsert(self, _pInputSelfClose, pRspInfo, _nRequestID, _bIsLast):
        """前置机对自对冲指令的同步应答；带错误码即视为 Failed。"""
        order_ref = str(getattr(_pInputSelfClose, "OptionSelfCloseRef", "") or "")
        if not order_ref:
            return

        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"❌ 自对冲指令前置机拒绝: ref={order_ref} 错误={pRspInfo.ErrorMsg}")
            try:
                self.option_action_tracker.transition(
                    order_ref,
                    OptionActionStatus.FAILED,
                    error_id=int(pRspInfo.ErrorID),
                    error_msg=str(pRspInfo.ErrorMsg),
                    error_source=OPTION_ERROR_SOURCE_FRONT,
                )
            except (KeyError, ValueError) as exc:
                self.logger.warning(f"自对冲状态机转移失败: {exc}")
            return

        try:
            self.option_action_tracker.transition(order_ref, OptionActionStatus.SUBMITTED)
        except (KeyError, ValueError) as exc:
            self.logger.warning(f"自对冲状态机转移失败: {exc}")

    def OnErrRtnOptionSelfCloseInsert(self, _pInputSelfClose, pRspInfo):
        """交易所对自对冲指令的异步拒绝；映射为 Failed 终态。"""
        order_ref = str(getattr(_pInputSelfClose, "OptionSelfCloseRef", "") or "")
        if not order_ref:
            return

        error_id = int(getattr(pRspInfo, "ErrorID", 0) or 0)
        error_msg = str(getattr(pRspInfo, "ErrorMsg", "") or "")
        self.logger.error(f"❌ 自对冲指令交易所拒绝: ref={order_ref} 错误={error_msg}")
        try:
            self.option_action_tracker.transition(
                order_ref,
                OptionActionStatus.FAILED,
                error_id=error_id,
                error_msg=error_msg,
                error_source=OPTION_ERROR_SOURCE_EXCHANGE,
            )
        except (KeyError, ValueError) as exc:
            self.logger.warning(f"自对冲状态机转移失败: {exc}")

    def OnRtnOptionSelfClose(self, pSelfClose):
        """自对冲指令的状态推送；按 ExecResult 推进至 Executed/Cancelled/Failed。"""
        order_ref = str(getattr(pSelfClose, "OptionSelfCloseRef", "") or "")
        if not order_ref:
            return

        # CTP ExecResult 取值与 ExecOrder 相同：
        # '0' 已发送 / '1' 已撤销 / '2' 自动撤销 / '3' 已经执行 / '4' 拒绝
        # 自对冲不区分"放弃"，只走 executed/cancelled/failed。
        exec_result = str(getattr(pSelfClose, "ExecResult", "") or "")
        target_status: OptionActionStatus | None = None
        if exec_result == "3":
            target_status = OptionActionStatus.EXECUTED
        elif exec_result in ("1", "2"):
            target_status = OptionActionStatus.CANCELLED
        elif exec_result == "4":
            target_status = OptionActionStatus.FAILED
        elif exec_result == "0":
            return  # 中间态
        else:
            self.logger.warning(f"OnRtnOptionSelfClose 未知 ExecResult={exec_result} ref={order_ref}")
            return

        try:
            self.option_action_tracker.transition(
                order_ref,
                target_status,
                error_id=int(getattr(pSelfClose, "ErrorID", 0) or 0)
                if target_status == OptionActionStatus.FAILED
                else 0,
                error_msg=str(getattr(pSelfClose, "StatusMsg", "") or ""),
            )
        except (KeyError, ValueError) as exc:
            self.logger.warning(f"自对冲状态机推进失败: ref={order_ref} 目标={target_status} 异常={exc}")

    def OnRspOptionSelfCloseAction(self, _pInputSelfCloseAction, pRspInfo, _nRequestID, _bIsLast):
        """自对冲撤销请求的应答；错误时回退到 Failed，否则等待 OnRtnOptionSelfClose。"""
        order_ref = str(getattr(_pInputSelfCloseAction, "OptionSelfCloseRef", "") or "")
        if not order_ref:
            return

        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"❌ 自对冲撤销失败: ref={order_ref} 错误={pRspInfo.ErrorMsg}")
            try:
                self.option_action_tracker.transition(
                    order_ref,
                    OptionActionStatus.FAILED,
                    error_id=int(pRspInfo.ErrorID),
                    error_msg=str(pRspInfo.ErrorMsg),
                    error_source=OPTION_ERROR_SOURCE_FRONT,
                )
            except (KeyError, ValueError) as exc:
                self.logger.warning(f"自对冲撤销状态机转移失败: {exc}")

"""CTP 期权指令模型与 OpenCTP 请求构造。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any

from openctp_ctp import thosttraderapi as td


class OptionActionType(str, Enum):
    """期权指令类型。"""

    EXERCISE = "exercise"
    ABANDON = "abandon"
    SELF_CLOSE = "self_close"


class OptionActionStatus(str, Enum):
    """期权指令状态。"""

    PENDING = "pending"
    SUBMITTED = "submitted"
    EXECUTED = "executed"
    ABANDONED = "abandoned"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OptionActionRecord:
    """当前进程提交的一条期权指令快照。"""

    order_ref: str
    instrument_id: str
    action: OptionActionType
    volume: int
    status: OptionActionStatus = OptionActionStatus.PENDING
    error_id: int = 0
    error_msg: str = ""
    error_source: str = ""
    submit_time: str | None = None
    finish_time: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def build_option_insert(
    *,
    broker_id: str,
    investor_id: str,
    order_ref: str,
    instrument_id: str,
    action: OptionActionType,
    volume: int,
) -> tuple[object, str]:
    """构造期权行权、放弃或自对冲请求。"""
    if action is OptionActionType.SELF_CLOSE:
        req = td.CThostFtdcInputOptionSelfCloseField()
        req.OptionSelfCloseRef = order_ref
        req.OptSelfCloseFlag = td.THOST_FTDC_OSCF_CloseSelfOptionPosition
        method = "ReqOptionSelfCloseInsert"
    else:
        req = td.CThostFtdcInputExecOrderField()
        req.ExecOrderRef = order_ref
        req.ActionType = td.THOST_FTDC_ACTP_Exec if action is OptionActionType.EXERCISE else td.THOST_FTDC_ACTP_Abandon
        req.PosiDirection = td.THOST_FTDC_PD_Long
        req.ReservePositionFlag = td.THOST_FTDC_EOPF_Reserve
        req.CloseFlag = td.THOST_FTDC_EOCF_NotToClose
        method = "ReqExecOrderInsert"
    req.BrokerID = broker_id
    req.InvestorID = investor_id
    req.InstrumentID = instrument_id
    req.Volume = volume
    req.HedgeFlag = td.THOST_FTDC_HF_Speculation
    return req, method


def build_option_cancel(record: OptionActionRecord, *, broker_id: str, investor_id: str) -> tuple[object, str]:
    """构造期权指令撤销请求。"""
    if record.action is OptionActionType.SELF_CLOSE:
        req = td.CThostFtdcInputOptionSelfCloseActionField()
        req.OptionSelfCloseRef = record.order_ref
        req.OptionSelfCloseSysID = str(record.extra.get("option_self_close_sys_id", ""))
        method = "ReqOptionSelfCloseAction"
    else:
        req = td.CThostFtdcInputExecOrderActionField()
        req.ExecOrderRef = record.order_ref
        req.ExecOrderSysID = str(record.extra.get("exec_order_sys_id", ""))
        method = "ReqExecOrderAction"
    req.BrokerID = broker_id
    req.InvestorID = investor_id
    req.InstrumentID = record.instrument_id
    req.ExchangeID = str(record.extra.get("exchange_id", ""))
    req.ActionFlag = td.THOST_FTDC_AF_Delete
    return req, method


def option_ref(row: Any) -> str:
    """从原生期权回报提取指令引用。"""
    return str(getattr(row, "ExecOrderRef", "") or getattr(row, "OptionSelfCloseRef", "") or "")


def accept_option_action(record: OptionActionRecord) -> OptionActionRecord:
    """返回柜台已受理的期权指令快照。"""
    return replace(record, status=OptionActionStatus.SUBMITTED)


def fail_option_action(record: OptionActionRecord, info: object, source: str) -> OptionActionRecord:
    """返回包含拒绝信息的期权指令终态。"""
    return replace(
        record,
        status=OptionActionStatus.FAILED,
        error_id=int(getattr(info, "ErrorID", 0) or 0),
        error_msg=str(getattr(info, "ErrorMsg", "") or ""),
        error_source=source,
        finish_time=datetime.now().isoformat(),
    )


def finish_option_action(record: OptionActionRecord, row: object) -> OptionActionRecord:
    """根据原生回报返回已执行或已放弃的期权指令终态。"""
    extra = dict(record.extra)
    extra.update(
        {
            "exchange_id": str(getattr(row, "ExchangeID", "") or ""),
            "exec_order_sys_id": str(getattr(row, "ExecOrderSysID", "") or "").strip(),
            "option_self_close_sys_id": str(getattr(row, "OptionSelfCloseSysID", "") or "").strip(),
        }
    )
    status = OptionActionStatus.ABANDONED if record.action is OptionActionType.ABANDON else OptionActionStatus.EXECUTED
    return replace(record, status=status, finish_time=datetime.now().isoformat(), extra=extra)


__all__ = ["OptionActionRecord", "OptionActionStatus", "OptionActionType"]

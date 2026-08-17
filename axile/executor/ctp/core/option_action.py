"""CTP 期权行权 / 放弃 / 自对冲指令模块.

封装 ``ReqExecOrderInsert`` / ``ReqExecOrderAction`` /
``ReqOptionSelfCloseInsert`` 三类请求的状态机、唯一标识与回调路由。
本模块**不直接依赖 trader.py**，而是把行权流水维护在独立的
:class:`OptionActionTracker` 中，供 :class:`CtpTrader` 在
``OnRspExecOrderInsert`` / ``OnErrRtnExecOrderInsert`` /
``OnRtnExecOrder`` 三个回调中分发。

设计要点
--------
- 单例 token：每个行权指令以 ``order_ref``（递增整数）唯一标识，
  与普通下单使用同一个 ref 序列以保持审计一致；状态机用 ``order_ref``
  做 key
- 状态机：::

    Pending → Submitted → Executed
                      → Abandoned
                      → Cancelling → Cancelled
                      → Failed
    Pending → Failed

- 错误码分发：``OnRspExecOrderInsert`` 携带前置机错误码；
  ``OnErrRtnExecOrderInsert`` 携带交易所错误码。两者均映射到
  ``Failed`` 终态，但日志记录上区分前置机 vs 交易所
- 撤销路径：``Submitted → Cancelling`` 由 ``cancel_option_action``
  发起；``OnRspExecOrderAction`` 写最终 Cancelled / Failed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Optional


class OptionActionType(str, Enum):
    """期权指令类型枚举."""

    EXERCISE = "exercise"  # 行权
    ABANDON = "abandon"  # 放弃
    SELF_CLOSE = "self_close"  # 自对冲


class OptionActionStatus(str, Enum):
    """期权指令状态机枚举."""

    PENDING = "pending"  # 已发出请求但未收到任何响应
    SUBMITTED = "submitted"  # 前置机受理（OnRspExecOrderInsert 无错）
    EXECUTED = "executed"  # 已执行（OnRtnExecOrder.ExecResult 表示已执行）
    ABANDONED = "abandoned"  # 已放弃
    CANCELLING = "cancelling"  # 撤销请求已发出，等待交易所应答
    CANCELLED = "cancelled"  # 已撤销
    FAILED = "failed"  # 前置机或交易所拒绝


_TERMINAL_STATUSES = frozenset(
    {
        OptionActionStatus.EXECUTED,
        OptionActionStatus.ABANDONED,
        OptionActionStatus.CANCELLED,
        OptionActionStatus.FAILED,
    }
)


# 期权指令错误来源标识：用作 OptionActionRecord.error_source 字段的值，
# 用于区分错误是由前置机（CTP API 同步应答）拒绝，还是由交易所异步拒绝。
OPTION_ERROR_SOURCE_FRONT = "front"  # 前置机（CTP API）拒绝
OPTION_ERROR_SOURCE_EXCHANGE = "exchange"  # 交易所拒绝


@dataclass
class OptionActionRecord:
    """单条期权指令的状态机快照与审计字段."""

    order_ref: str
    instrument_id: str
    action: OptionActionType
    volume: int
    status: OptionActionStatus = OptionActionStatus.PENDING
    error_id: int = 0
    error_msg: str = ""
    error_source: str = ""  # OPTION_ERROR_SOURCE_FRONT | OPTION_ERROR_SOURCE_EXCHANGE | ""
    submit_time: Optional[str] = None
    finish_time: Optional[str] = None
    extra: dict[str, object] = field(default_factory=dict)


_VALID_TRANSITIONS: dict[OptionActionStatus, frozenset[OptionActionStatus]] = {
    OptionActionStatus.PENDING: frozenset({OptionActionStatus.SUBMITTED, OptionActionStatus.FAILED}),
    OptionActionStatus.SUBMITTED: frozenset(
        {
            OptionActionStatus.EXECUTED,
            OptionActionStatus.ABANDONED,
            OptionActionStatus.CANCELLING,
            # 直接到 CANCELLED 的合法路径：
            # CTP 自动撤销（如盘后清理）或者系统侧发起的撤销，会跳过本地
            # CANCELLING 中间态。OnRtnExecOrder 收到 ExecResult='1'/'2' 时
            # 直接推到终态。
            OptionActionStatus.CANCELLED,
            OptionActionStatus.FAILED,
        }
    ),
    OptionActionStatus.CANCELLING: frozenset({OptionActionStatus.CANCELLED, OptionActionStatus.FAILED}),
    # 终态不可转出
    OptionActionStatus.EXECUTED: frozenset(),
    OptionActionStatus.ABANDONED: frozenset(),
    OptionActionStatus.CANCELLED: frozenset(),
    OptionActionStatus.FAILED: frozenset(),
}


class OptionActionTracker:
    """期权指令状态机维护与查询入口.

    线程安全：所有读写操作通过内部锁串行化，可被回调线程与算法线程
    并发访问。
    """

    def __init__(self) -> None:
        self._records: dict[str, OptionActionRecord] = {}
        self._lock: Lock = Lock()

    def register(
        self,
        *,
        order_ref: str,
        instrument_id: str,
        action: OptionActionType,
        volume: int,
        submit_time: Optional[str] = None,
    ) -> OptionActionRecord:
        """登记一条新的期权指令，状态置为 Pending."""
        with self._lock:
            if order_ref in self._records:
                raise ValueError(f"order_ref={order_ref} 已存在重复行权指令")
            record = OptionActionRecord(
                order_ref=order_ref,
                instrument_id=instrument_id,
                action=action,
                volume=volume,
                submit_time=submit_time,
            )
            self._records[order_ref] = record
            return record

    def get(self, order_ref: str) -> Optional[OptionActionRecord]:
        """读取指定流水的状态快照（不变更状态机）."""
        with self._lock:
            return self._records.get(order_ref)

    def transition(
        self,
        order_ref: str,
        new_status: OptionActionStatus,
        *,
        error_id: int = 0,
        error_msg: str = "",
        error_source: str = "",
        finish_time: Optional[str] = None,
        extra: Optional[dict[str, object]] = None,
    ) -> OptionActionRecord:
        """
        推进状态机；非法转移会抛 ValueError.

        Parameters
        ----------
        order_ref : str
            指令唯一编号。
        new_status : OptionActionStatus
            目标状态。
        error_id : int, default=0
            错误码（仅 ``Failed`` 转移有效）。
        error_msg : str, default=""
            错误描述。
        error_source : str, default=""
            错误来源标记 ``"front"`` / ``"exchange"``（推荐使用模块级常量
            :data:`OPTION_ERROR_SOURCE_FRONT` / :data:`OPTION_ERROR_SOURCE_EXCHANGE`）。
        finish_time : str | None, optional
            进入终态时的时间戳。
        extra : dict | None, optional
            合并到 ``record.extra`` 的附加字段。

        Returns
        -------
        OptionActionRecord
            转移后的状态快照。
        """
        with self._lock:
            record = self._records.get(order_ref)
            if record is None:
                raise KeyError(f"order_ref={order_ref} 未登记，无法转移到 {new_status}")

            allowed = _VALID_TRANSITIONS.get(record.status, frozenset())
            if new_status not in allowed:
                raise ValueError(
                    f"order_ref={order_ref}: 非法状态转移 {record.status} → {new_status}; 允许集合={set(allowed)}"
                )

            record.status = new_status
            if error_id:
                record.error_id = error_id
            if error_msg:
                record.error_msg = error_msg
            if error_source:
                record.error_source = error_source
            if finish_time and new_status in _TERMINAL_STATUSES:
                record.finish_time = finish_time
            if extra:
                record.extra.update(extra)
            return record

    def is_terminal(self, order_ref: str) -> bool:
        """判断流水是否进入终态."""
        with self._lock:
            record = self._records.get(order_ref)
            if record is None:
                return False
            return record.status in _TERMINAL_STATUSES

    def list_active(self) -> list[OptionActionRecord]:
        """列出所有未进入终态的指令快照."""
        with self._lock:
            return [r for r in self._records.values() if r.status not in _TERMINAL_STATUSES]

    def all_records(self) -> list[OptionActionRecord]:
        """列出全部已登记指令的快照（用于审计 / 调试）."""
        with self._lock:
            return list(self._records.values())


def operation_key(action: OptionActionType) -> str:
    """将 ``OptionActionType`` 映射为 account_control operation key."""
    return {
        OptionActionType.EXERCISE: "option_exercise",
        OptionActionType.ABANDON: "option_abandon",
        OptionActionType.SELF_CLOSE: "option_self_close",
    }[action]

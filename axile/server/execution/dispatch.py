"""执行后端分发策略."""

from enum import StrEnum

from axile.channels import get_channel
from axile.common.trade_channel import TradeChannel


class ExecutionBackendKind(StrEnum):
    """
    执行后端类型枚举.

    Attributes
    ----------
    THREAD : str
        在线程中执行阻塞执行器逻辑。
    PROCESS : str
        通过多进程 worker backend 执行。
    """

    THREAD = "thread"
    PROCESS = "process"


def resolve_execution_backend_kind(trade_channel: TradeChannel) -> ExecutionBackendKind:
    """
    解析指定交易渠道应使用的执行后端类型.

    Parameters
    ----------
    trade_channel : TradeChannel
        当前账户所属的交易渠道。

    Returns
    -------
    ExecutionBackendKind
        对应渠道默认使用的执行后端类型。
    """
    return ExecutionBackendKind(get_channel(trade_channel).execution_backend)

"""执行后端分发策略测试。"""

from axile.common.trade_channel import TradeChannel
from axile.server.execution.dispatch import ExecutionBackendKind, resolve_execution_backend_kind


def test_resolve_execution_backend_kind_defaults_by_channel() -> None:
    """不同渠道应映射到预期的默认执行后端。"""
    assert resolve_execution_backend_kind(TradeChannel.GM) == ExecutionBackendKind.PROCESS
    assert resolve_execution_backend_kind(TradeChannel.CTP) == ExecutionBackendKind.PROCESS

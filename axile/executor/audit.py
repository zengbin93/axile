"""执行器层使用的审计输出协议."""

from __future__ import annotations

from typing import Protocol

from axile.common.trade_channel import TradeChannel


class ExecutionAuditSink(Protocol):
    """
    定义 execution runtime 对外发出审计事件与附件的输出协议.

    Notes
    -----
    ``axile.executor`` 只依赖该协议，不依赖任何具体的服务端持久化实现。
    """

    def append_event(
        self,
        *,
        execution_id: str,
        account_id: int,
        channel: TradeChannel,
        algorithm: str,
        event_type: object,
        status: object,
        reason_family: object,
        reason_code: str,
        symbol: str | None = None,
        intent_id: str | None = None,
        order_id: str | None = None,
        client_order_id: str | None = None,
        ts_exchange: str | None = None,
        seq: int = 0,
        details: dict[str, object] | None = None,
    ) -> bool:
        """
        输出一条 execution 审计事件.

        Returns
        -------
        bool
            审计事件成功输出时返回 ``True``。
        """

    def append_artifact(
        self,
        *,
        execution_id: str,
        artifact_type: object,
        content: dict[str, object],
    ) -> bool:
        """
        输出一条 execution 审计附件.

        Returns
        -------
        bool
            审计附件成功输出时返回 ``True``。
        """

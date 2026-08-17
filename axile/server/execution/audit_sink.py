"""服务端 execution 审计输出 sink."""

from __future__ import annotations

from axile.common.trade_channel import TradeChannel
from axile.executor.audit import ExecutionAuditSink
from axile.server.execution_audit import append_execution_artifact_sync, append_execution_event_sync


class ServerExecutionAuditSink(ExecutionAuditSink):
    """
    将 execution 审计输出写入服务端持久化层.

    Notes
    -----
    该实现是 ``axile.executor.audit.ExecutionAuditSink`` 在 server 侧的具体适配器。
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
        同步写入 execution 审计事件.

        Returns
        -------
        bool
            审计事件成功写入时返回 ``True``。
        """
        return append_execution_event_sync(
            execution_id=execution_id,
            account_id=account_id,
            channel=channel,
            algorithm=algorithm,
            event_type=event_type,
            status=status,
            reason_family=reason_family,
            reason_code=reason_code,
            symbol=symbol,
            intent_id=intent_id,
            order_id=order_id,
            client_order_id=client_order_id,
            ts_exchange=ts_exchange,
            seq=seq,
            details=details,
        )

    def append_artifact(
        self,
        *,
        execution_id: str,
        artifact_type: object,
        content: dict[str, object],
    ) -> bool:
        """
        同步写入 execution 审计附件.

        Returns
        -------
        bool
            审计附件成功写入时返回 ``True``。
        """
        return append_execution_artifact_sync(
            execution_id=execution_id,
            artifact_type=artifact_type,
            content=content,
        )


def build_server_execution_audit_sink() -> ExecutionAuditSink:
    """
    构造服务端 execution 审计输出 sink.

    Returns
    -------
    ExecutionAuditSink
        可注入执行器 runtime 的服务端审计输出 sink。
    """
    return ServerExecutionAuditSink()

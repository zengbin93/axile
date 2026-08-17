"""规范化 worker 成功、失败与终止响应.

该模块负责把执行器返回值和异常对象收敛为跨进程协议字段，确保
主进程只依赖稳定、可序列化的响应形状。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import cast

from loguru import logger

from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.termination import ExecutionTerminated
from axile.server.db.models import Account
from axile.server.execution.worker_backend.protocol import (
    WorkerBackendErrorPayload,
    WorkerBackendRequest,
    WorkerBackendResponse,
)


def _camel_to_snake(name: str) -> str:
    """将异常类名转换为协议使用的 snake_case 标识."""
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return normalized or "runtime_error"


def _build_error_payload(exc: Exception) -> WorkerBackendErrorPayload:
    """
    构造 worker 结构化错误载荷。

    Parameters
    ----------
    exc : Exception
        当前捕获的异常对象。

    Returns
    -------
    WorkerBackendErrorPayload
        结构化错误信息。
    """
    # 错误响应只保留协议稳定字段，避免把不可序列化的异常细节直接泄漏到进程边界外。
    return WorkerBackendErrorPayload(
        type=_camel_to_snake(exc.__class__.__name__),
        message=str(exc) or exc.__class__.__name__,
        retryable=isinstance(exc, TimeoutError),
    )


def _build_terminated_response(
    *,
    request_id: str,
    account: Account,
    exc: ExecutionTerminated,
) -> WorkerBackendResponse:
    """
    构造 worker terminated 响应。

    Parameters
    ----------
    request_id : str
        当前请求标识。
    account : Account
        当前请求绑定的账户对象。
    exc : ExecutionTerminated
        终止异常对象。

    Returns
    -------
    WorkerBackendResponse
        结构化 terminated 响应。
    """
    # terminated 不是普通 error；主进程需要拿到 mode / acked_at / trigger 等字段
    # 继续驱动上层状态机与审计——worker 进程内触发的总超时也要能被主进程识别出来。
    return WorkerBackendResponse(
        request_id=request_id,
        kind="terminated",
        channel_type=account.trade_channel,
        reason=exc.reason,
        mode=exc.mode,
        acked_at=exc.acked_at,
        trigger=exc.trigger,
        cancel_failed_order_ids=exc.cancel_failed_order_ids,
    )


def _dump_output_payload(output: UnifiedStandardOutput) -> dict[str, object]:
    """序列化 worker 标准输出载荷.

    Parameters
    ----------
    output : UnifiedStandardOutput
        执行器返回的统一输出对象。

    Returns
    -------
    dict[str, object]
        适合跨进程传输和审计落盘的 JSON 兼容字典。
    """
    return cast("dict[str, object]", output.model_dump(mode="json"))


def _build_result_response(*, request_id: str, result: dict[str, object]) -> WorkerBackendResponse:
    """
    构造 worker 成功结果响应。

    Parameters
    ----------
    request_id : str
        当前请求标识。
    result : dict[str, object]
        序列化后的结果载荷。

    Returns
    -------
    WorkerBackendResponse
        成功结果响应。
    """
    # 这里返回的必须是纯字典载荷，主进程不会共享 Python 对象实例，只认协议字段。
    return WorkerBackendResponse(
        request_id=request_id,
        kind="result",
        output_payload=result,
    )


def _handle_worker_command_failure(
    *,
    request: WorkerBackendRequest,
    account: Account,
    algorithm_name: str,
    executor: object | None,
    trigger_source: str,
    exc: Exception,
    log_message: str,
    append_failed_audit: Callable[..., None],
) -> WorkerBackendResponse:
    """
    补写失败审计并返回统一错误响应。

    Parameters
    ----------
    request : WorkerBackendRequest
        当前 worker 请求。
    account : Account
        当前请求绑定的账户对象。
    algorithm_name : str
        本次请求解析出的算法名。
    executor : object | None
        当前请求使用的执行器；失败前可能尚未创建。
    trigger_source : str
        当前请求的触发来源。
    exc : Exception
        当前捕获的异常对象。
    log_message : str
        需要输出的日志消息前缀。
    append_failed_audit : Callable[..., None]
        当前请求应使用的失败审计写入函数。

    Returns
    -------
    WorkerBackendResponse
        统一错误响应。
    """
    # 先补失败审计再回错误响应，这样即使主进程马上抛错，审计流里也已经有失败事件。
    error_payload = _build_error_payload(exc)
    append_failed_audit(
        account=account,
        execution_id=request.execution_id,
        algorithm_name=algorithm_name,
        executor=executor,
        error=error_payload,
        trigger_source=trigger_source,
    )
    logger.exception("{}: {}", log_message, exc)
    return WorkerBackendResponse(
        request_id=request.request_id,
        kind="error",
        error=error_payload,
        channel_type=account.trade_channel,
    )

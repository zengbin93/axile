"""运行多进程执行 worker 的命令分派入口.

该文件只保留 worker 命令级骨架：解析请求、准备执行器、写审计、
回传响应和清理运行时。更细的请求解析、状态复用与响应规范化逻辑
分别下沉到相邻辅助模块。
"""

from __future__ import annotations

from multiprocessing.connection import Connection
from typing import cast

from loguru import logger

from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.termination import ExecutionTerminated
from axile.server.db.models import Account
from axile.server.execution.worker_backend.protocol import (
    WorkerBackendErrorPayload,
    WorkerBackendRequest,
    WorkerBackendResponse,
)
from axile.server.execution.worker_backend.worker_audit import (
    _append_empty_positions_pre_execute_audit,
    _append_failed_audit,
    _append_success_audit,
    _append_trade_pre_execute_audit,
)
from axile.server.execution.worker_backend.worker_requests import (
    _parse_empty_positions_request,
    _parse_execute_trade_request,
)
from axile.server.execution.worker_backend.worker_responses import (
    _build_result_response,
    _build_terminated_response,
    _dump_output_payload,
    _handle_worker_command_failure,
)
from axile.server.execution.worker_backend.worker_state import (
    _close_executor,
    _finalize_executor,
    _resolve_executor,
    _resolve_prepared_executor,
    _WorkerBackendState,
)


def _handle_prepare(request: WorkerBackendRequest, state: _WorkerBackendState) -> WorkerBackendResponse:
    """创建或复用账户执行器，并返回通道准备结果。"""
    account = Account.model_validate(request.account_payload)
    expected = str(request.payload.get("expected_trading_day", "") or "") or None
    try:
        executor = _resolve_executor(state, account, expected)
        return WorkerBackendResponse(
            request_id=request.request_id,
            kind="result",
            output_payload={
                "ready": True,
                "trading_day": str(getattr(executor, "_trading_day", "") or ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 - IPC 边界统一返回结构化错误
        return WorkerBackendResponse(
            request_id=request.request_id,
            kind="error",
            channel_type=account.trade_channel,
            error=WorkerBackendErrorPayload(type="channel_not_ready", message=str(exc), retryable=True),
        )


def _capture_before_account_snapshot(executor: object) -> dict[str, object] | None:
    """执行前拉取一次账户快照作为对账基线（worker 同步路径）.

    Parameters
    ----------
    executor : object
        已就绪的执行器实例。

    Returns
    -------
    dict[str, object] | None
        账户快照的 JSON 化内容；读取失败或执行器不支持时返回 ``None``（由下游按
        ``unavailable`` 处理），不影响执行主线。
    """
    get_account_assets = getattr(executor, "get_account_assets", None)
    if not callable(get_account_assets):
        return None
    try:
        assets = cast(UnifiedAccountAssets, get_account_assets())
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"执行前账户快照读取失败，将标记为 unavailable: {exc}")
        return None
    return cast("dict[str, object]", assets.model_dump(mode="json"))


def _handle_execute_trade(
    request: WorkerBackendRequest,
    state: _WorkerBackendState,
) -> WorkerBackendResponse:
    """处理单次 `execute_trade` 命令.

    Parameters
    ----------
    request : WorkerBackendRequest
        主进程发来的调仓命令。
    state : _WorkerBackendState
        worker 当前缓存状态。

    Returns
    -------
    WorkerBackendResponse
        对应的成功、终止或失败响应。
    """
    context = _parse_execute_trade_request(request)
    executor = None
    try:
        # worker 入口只保留命令级主线，具体的状态准备和审计细节都下沉到专用模块。
        executor = _resolve_prepared_executor(
            state=state,
            account=context.account,
            execution_id=request.execution_id,
            audit_context=context.audit_context,
        )
        before_account_assets = _capture_before_account_snapshot(executor)
        _append_trade_pre_execute_audit(
            account=context.account,
            execution_id=request.execution_id,
            algorithm_name=context.algorithm_name,
            trigger_source=context.trigger_source,
            strategy_count=context.strategy_count,
            audit_input=context.audit_input,
            standard_input=context.standard_input,
            executor=executor,
            before_account_assets=before_account_assets,
        )
        execute = getattr(executor, "execute")
        output = cast(
            UnifiedStandardOutput,
            execute(
                context.standard_input,
                cleanup=False,
                retain_runtime=True,
            ),
        )
        result = _dump_output_payload(output)
        _append_success_audit(
            account=context.account,
            execution_id=request.execution_id,
            algorithm_name=context.algorithm_name,
            output=output,
            result=result,
            executor=executor,
            include_trade_rule_snapshots=True,
            before_account_assets=before_account_assets,
        )
        return _build_result_response(request_id=request.request_id, result=result)
    except ExecutionTerminated as exc:
        return _build_terminated_response(
            request_id=request.request_id,
            account=context.account,
            exc=exc,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_worker_command_failure(
            request=request,
            account=context.account,
            algorithm_name=context.algorithm_name,
            executor=executor,
            trigger_source=context.trigger_source,
            exc=exc,
            log_message="worker backend execute_trade 失败",
            append_failed_audit=_append_failed_audit,
        )
    finally:
        _finalize_executor(executor)


def _handle_empty_positions(
    request: WorkerBackendRequest,
    state: _WorkerBackendState,
) -> WorkerBackendResponse:
    """处理单次 `empty_positions` 命令.

    Parameters
    ----------
    request : WorkerBackendRequest
        主进程发来的清仓命令。
    state : _WorkerBackendState
        worker 当前缓存状态。

    Returns
    -------
    WorkerBackendResponse
        对应的成功、终止或失败响应。
    """
    context = _parse_empty_positions_request(request)
    executor = None
    try:
        # 清仓和调仓共用同一套外层骨架，差异只保留在请求解析、pre-audit 和真实调用上。
        executor = _resolve_prepared_executor(
            state=state,
            account=context.account,
            execution_id=request.execution_id,
            audit_context=context.audit_context,
        )
        before_account_assets = _capture_before_account_snapshot(executor)
        _append_empty_positions_pre_execute_audit(
            account=context.account,
            execution_id=request.execution_id,
            algorithm_name=context.algorithm_name,
            executor=executor,
            before_account_assets=before_account_assets,
        )
        empty_positions = getattr(executor, "empty_positions")
        output = cast(
            UnifiedStandardOutput,
            empty_positions(cleanup=False, retain_runtime=True, **context.empty_kwargs),
        )
        result = _dump_output_payload(output)
        _append_success_audit(
            account=context.account,
            execution_id=request.execution_id,
            algorithm_name=context.algorithm_name,
            output=output,
            result=result,
            executor=executor,
            include_trade_rule_snapshots=False,
            audit_input=context.audit_input,
            before_account_assets=before_account_assets,
        )
        return _build_result_response(request_id=request.request_id, result=result)
    except ExecutionTerminated as exc:
        return _build_terminated_response(
            request_id=request.request_id,
            account=context.account,
            exc=exc,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_worker_command_failure(
            request=request,
            account=context.account,
            algorithm_name=context.algorithm_name,
            executor=executor,
            trigger_source="empty_positions",
            exc=exc,
            log_message="worker backend empty_positions 失败",
            append_failed_audit=_append_failed_audit,
        )
    finally:
        _finalize_executor(executor)


def _handle_shutdown(
    request: WorkerBackendRequest,
    state: _WorkerBackendState,
) -> WorkerBackendResponse:
    """处理 worker 显式关闭请求.

    Parameters
    ----------
    request : WorkerBackendRequest
        当前关闭请求。
    state : _WorkerBackendState
        worker 运行时状态。

    Returns
    -------
    WorkerBackendResponse
        关闭确认响应。
    """
    reason = str(request.payload.get("reason", "manager_shutdown"))
    if state.executor is not None:
        _close_executor(state.executor)
        state.executor = None
        state.account_id = None
        state.config_signature = None
    return WorkerBackendResponse(
        request_id=request.request_id,
        kind="result",
        output_payload={"shutdown": True, "reason": reason},
    )


def _handle_worker_request(
    request: WorkerBackendRequest,
    state: _WorkerBackendState,
) -> WorkerBackendResponse:
    """分派并执行单个 worker 请求.

    Parameters
    ----------
    request : WorkerBackendRequest
        主进程发来的请求。
    state : _WorkerBackendState
        worker 当前运行时状态。

    Returns
    -------
    WorkerBackendResponse
        对应响应对象。
    """
    if request.command == "prepare":
        return _handle_prepare(request, state)
    if request.command == "execute_trade":
        return _handle_execute_trade(request, state)
    if request.command == "empty_positions":
        return _handle_empty_positions(request, state)
    return _handle_shutdown(request, state)


def run_worker_backend_loop(connection: Connection, account_id: int) -> None:
    """运行多进程 worker 的阻塞请求循环.

    Parameters
    ----------
    connection : Connection
        与主进程通信的管道连接。
    account_id : int
        该 worker 绑定的账户标识。
    """
    state = _WorkerBackendState(account_id=account_id)
    logger.info("[WORKER-BACKEND] worker 启动 | account_id={}", account_id)
    try:
        while True:
            try:
                raw_request = connection.recv()
            except EOFError:
                break

            if raw_request is None:
                break

            request = cast(WorkerBackendRequest, raw_request)
            response = _handle_worker_request(request, state)
            # 先回响应，再按 shutdown 命令退出循环，保证主进程一定能收到确认消息。
            connection.send(response)
            if request.command == "shutdown":
                break
    finally:
        _close_executor(state.executor)
        connection.close()
        logger.info("[WORKER-BACKEND] worker 退出 | account_id={}", account_id)

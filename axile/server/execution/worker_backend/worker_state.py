"""管理 worker 内执行器缓存与请求级运行时准备.

该模块把“可跨请求复用的执行器实例”和“只能按请求重建的审计/
账户控制上下文”明确拆开，避免复用连接时把上一条命令的运行时
状态意外带入下一条命令。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from axile.server.db.models import Account
from axile.server.execution.audit_sink import build_server_execution_audit_sink
from axile.server.execution.execution_account_control import (
    build_account_control_guard,
    flush_account_control_records,
)
from axile.server.execution.factory import create_executor_instance


@dataclass(slots=True)
class _WorkerBackendState:
    """保存多进程 worker 内可复用的执行器缓存.

    Notes
    -----
    这里缓存的是执行器实例及其复用判定键，不缓存请求级审计上下文
    或账户控制 guard。
    """

    executor: object | None = None
    account_id: int | None = None
    config_signature: str | None = None


def _close_executor(executor: object | None) -> None:
    """清理请求级状态并释放缓存执行器。"""
    if executor is None:
        return
    _finalize_executor(executor)
    stop = getattr(executor, "stop", None)
    if callable(stop):
        stop()
        return
    close = getattr(executor, "close", None)
    if callable(close):
        close()


def _config_signature(account: Account) -> str:
    """生成账户配置的稳定签名，用于判定执行器是否可复用.

    Parameters
    ----------
    account : Account
        待生成配置签名的账户对象。

    Returns
    -------
    str
        仅由账户配置字段决定的稳定签名。
    """
    return json.dumps(account.account_config, sort_keys=True, ensure_ascii=False)


def _resolve_executor(
    state: _WorkerBackendState,
    account: Account,
    expected_trading_day: str | None = None,
) -> object:
    """
    解析当前请求应复用的执行器实例。

    Parameters
    ----------
    state : _WorkerBackendState
        worker 当前缓存状态。
    account : Account
        本次请求绑定的账户对象。

    Returns
    -------
    object
        复用或新建后的执行器实例。
    """
    signature = _config_signature(account)
    # worker 只在“账户相同且配置签名相同”时复用执行器，避免把旧连接状态带到新配置里。
    if state.executor is not None and state.account_id == account.id and state.config_signature == signature:
        verify = getattr(state.executor, "_verify_connection", None)
        connected = not callable(verify) or bool(verify())
        trading_day = str(getattr(state.executor, "_trading_day", "") or "")
        if connected and (not expected_trading_day or trading_day == expected_trading_day):
            return state.executor

    if state.executor is not None:
        _close_executor(state.executor)
    state.executor = None
    state.account_id = None
    state.config_signature = None
    state.executor = create_executor_instance(account)
    state.account_id = account.id
    state.config_signature = signature
    if expected_trading_day:
        trading_day = str(getattr(state.executor, "_trading_day", "") or "")
        if trading_day != expected_trading_day:
            _close_executor(state.executor)
            state.executor = None
            state.account_id = None
            state.config_signature = None
            raise RuntimeError(f"柜台交易日不匹配: expected={expected_trading_day}, actual={trading_day or 'unknown'}")
    return state.executor


def _prepare_executor(
    *,
    executor: object,
    account: Account,
    execution_id: str | None,
    audit_context: dict[str, object],
) -> None:
    """
    为当前请求准备执行器的审计与账户控制运行时。

    Parameters
    ----------
    executor : object
        当前请求要执行的执行器实例。
    account : Account
        关联账户对象。
    execution_id : str | None
        当前执行标识。
    audit_context : dict[str, object]
        需要绑定到执行器的审计上下文。

    Notes
    -----
    即使执行器实例被缓存复用，请求级 audit sink、账户控制 guard
    和 runtime 准备步骤也必须逐次重绑。
    """
    # 这里每次请求都重新绑定 audit / guard，即使执行器实例被复用，请求级上下文也不能复用。
    set_audit_context = getattr(executor, "set_audit_context", None)
    if callable(set_audit_context):
        set_audit_context(audit_context)

    set_audit_sink = getattr(executor, "set_audit_sink", None)
    if callable(set_audit_sink):
        set_audit_sink(build_server_execution_audit_sink())

    guard = asyncio.run(build_account_control_guard(account, execution_id))
    set_account_control_guard = getattr(executor, "set_account_control_guard", None)
    if callable(set_account_control_guard):
        set_account_control_guard(guard)

    prepare_execution_runtime = getattr(executor, "prepare_execution_runtime", None)
    if callable(prepare_execution_runtime):
        prepare_execution_runtime()


def _resolve_prepared_executor(
    *,
    state: _WorkerBackendState,
    account: Account,
    execution_id: str | None,
    audit_context: dict[str, object],
) -> object:
    """
    解析并准备本次请求要使用的执行器实例。

    Parameters
    ----------
    state : _WorkerBackendState
        worker 当前缓存状态。
    account : Account
        本次请求绑定的账户对象。
    execution_id : str | None
        当前执行标识。
    audit_context : dict[str, object]
        需要绑定到执行器的审计上下文。

    Returns
    -------
    object
        已完成请求级准备的执行器实例。
    """
    executor = _resolve_executor(state, account)
    _prepare_executor(
        executor=executor,
        account=account,
        execution_id=execution_id,
        audit_context=audit_context,
    )
    return executor


def _finalize_executor(executor: object | None) -> None:
    """
    清理执行器上的运行时与账户控制残留状态。

    Parameters
    ----------
    executor : object | None
        当前需要清理的执行器实例；为空时忽略。

    Notes
    -----
    账户控制记录必须先落库，再清理执行器 runtime，否则这次请求
    期间累积的 guard 状态会在清理后丢失。
    """
    if executor is None:
        return

    # flush 记录必须先于 clear runtime，否则 guard 上累积的事件会被直接丢掉。
    asyncio.run(flush_account_control_records(executor))
    clear_execution_runtime = getattr(executor, "clear_execution_runtime", None)
    if callable(clear_execution_runtime):
        clear_execution_runtime()

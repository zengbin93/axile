"""
提供账户控制相关的装饰器与调用包装函数.

Notes
-----
该模块负责在真实对外交互前后接入账户控制守卫，并统一记录放行或失败结果。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from axile.executor.account_control.decorator_registry import (
    build_registered_operation,
    register_operation_bootstrap,
    register_or_validate_operation,
)
from axile.executor.account_control.decorator_support import (
    normalize_metadata,
    record_controlled_failure,
    record_controlled_success,
    resolve_controlled_call_context,
)
from axile.executor.account_control.registry import (
    register_default_registry_bootstrap,
)

P = ParamSpec("P")
R = TypeVar("R")

type MetadataResolver = Callable[[inspect.BoundArguments], Mapping[str, object] | None]
type ResultMetadataResolver[R] = Callable[[R], Mapping[str, object] | None]
type SuccessOutcomeResolver[R] = str | Callable[[R], str]


def run_controlled_call[R](
    *,
    guard: Any | None,
    operation: str,
    call: Callable[[], R],
    symbol: str | None = None,
    metadata: Mapping[str, object] | None = None,
    success_outcome: SuccessOutcomeResolver[R] = "succeeded",
    result_metadata_resolver: ResultMetadataResolver[R] | None = None,
) -> R:
    """
    执行同步账户控制调用并记录结果.

    Parameters
    ----------
    guard : Any | None
        当前对象绑定的账户控制守卫；为空时直接执行调用。
    operation : str
        当前调用对应的操作键。
    call : Callable[[], R]
        实际需要执行的同步调用。
    symbol : str | None, optional
        本次调用关联的交易标的代码。
    metadata : Mapping[str, object] | None, optional
        需要随事件一起记录的附加元数据。
    success_outcome : SuccessOutcomeResolver[R], optional
        成功时写入事件的 outcome，支持固定字符串或基于返回值的解析函数。
    result_metadata_resolver : ResultMetadataResolver[R] | None, optional
        基于返回值补充事件元数据的解析函数。

    Returns
    -------
    R
        原始调用的返回值。

    Raises
    ------
    Exception
        原始调用抛出的异常会原样向上抛出，同时事件 outcome 会记为
        ``downstream_error``。
    """
    resolved_metadata = normalize_metadata(metadata)
    if guard is None:
        return call()

    attempt = guard.begin_operation(
        operation,
        symbol=symbol,
        metadata=resolved_metadata,
    )
    try:
        result = call()
    except Exception:
        record_controlled_failure(attempt=attempt, metadata=resolved_metadata)
        raise

    record_controlled_success(
        attempt=attempt,
        result=result,
        metadata=resolved_metadata,
        success_outcome=success_outcome,
        result_metadata_resolver=result_metadata_resolver,
    )
    return result


async def run_controlled_async_call[R](
    *,
    guard: Any | None,
    operation: str,
    call: Callable[[], Awaitable[R]],
    symbol: str | None = None,
    metadata: Mapping[str, object] | None = None,
    success_outcome: SuccessOutcomeResolver[R] = "succeeded",
    result_metadata_resolver: ResultMetadataResolver[R] | None = None,
) -> R:
    """
    执行异步账户控制调用并记录结果.

    Parameters
    ----------
    guard : Any | None
        当前对象绑定的账户控制守卫；为空时直接执行调用。
    operation : str
        当前调用对应的操作键。
    call : Callable[[], Awaitable[R]]
        实际需要执行的异步调用。
    symbol : str | None, optional
        本次调用关联的交易标的代码。
    metadata : Mapping[str, object] | None, optional
        需要随事件一起记录的附加元数据。
    success_outcome : SuccessOutcomeResolver[R], optional
        成功时写入事件的 outcome，支持固定字符串或基于返回值的解析函数。
    result_metadata_resolver : ResultMetadataResolver[R] | None, optional
        基于返回值补充事件元数据的解析函数。

    Returns
    -------
    R
        原始异步调用的返回值。

    Raises
    ------
    Exception
        原始调用抛出的异常会原样向上抛出，同时事件 outcome 会记为
        ``downstream_error``。
    """
    resolved_metadata = normalize_metadata(metadata)
    if guard is None:
        return await call()

    attempt = guard.begin_operation(
        operation,
        symbol=symbol,
        metadata=resolved_metadata,
    )
    try:
        result = await call()
    except Exception:
        record_controlled_failure(attempt=attempt, metadata=resolved_metadata)
        raise

    record_controlled_success(
        attempt=attempt,
        result=result,
        metadata=resolved_metadata,
        success_outcome=success_outcome,
        result_metadata_resolver=result_metadata_resolver,
    )
    return result


def controlled_operation(
    operation: str,
    *,
    groups: tuple[str, ...] = (),
    symbol_arg: str | None = None,
    metadata_resolver: MetadataResolver | None = None,
    success_outcome: SuccessOutcomeResolver[Any] = "succeeded",
    result_metadata_resolver: ResultMetadataResolver[Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    为公开行为或叶子远端操作附加账户控制.

    Parameters
    ----------
    operation : str
        需要登记并受控的操作键。
    groups : tuple[str, ...], optional
        当前操作所属的共享节流组。
    symbol_arg : str | None, optional
        从函数参数中解析交易标的代码时使用的参数名。
    metadata_resolver : MetadataResolver | None, optional
        从调用参数中提取事件元数据的解析函数。
    success_outcome : SuccessOutcomeResolver[Any], optional
        成功时使用的 outcome 或其解析函数。
    result_metadata_resolver : ResultMetadataResolver[Any] | None, optional
        根据返回值补充事件元数据的解析函数。

    Returns
    -------
    Callable[[Callable[P, R]], Callable[P, R]]
        可包装同步或异步函数的装饰器。

    Notes
    -----
    装饰器在定义阶段会尝试向默认注册表登记 operation，并在调用阶段自动
    从宿主对象解析 guard。
    """
    registered_operation = build_registered_operation(
        operation,
        groups=groups,
    )
    register_or_validate_operation(registered_operation)
    register_default_registry_bootstrap(lambda: register_operation_bootstrap(registered_operation))

    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        signature = inspect.signature(function)

        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                bound_arguments = signature.bind_partial(*args, **kwargs)
                call_context = resolve_controlled_call_context(
                    bound_arguments=bound_arguments,
                    owner=args[0] if args else None,
                    symbol_arg=symbol_arg,
                    metadata_resolver=metadata_resolver,
                )

                async def _call() -> R:
                    return await function(*args, **kwargs)

                return await run_controlled_async_call(
                    guard=call_context.guard,
                    operation=registered_operation.key,
                    symbol=call_context.symbol,
                    metadata=call_context.metadata,
                    call=_call,
                    success_outcome=success_outcome,
                    result_metadata_resolver=result_metadata_resolver,
                )

            return cast("Callable[P, R]", async_wrapper)

        @wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound_arguments = signature.bind_partial(*args, **kwargs)
            call_context = resolve_controlled_call_context(
                bound_arguments=bound_arguments,
                owner=args[0] if args else None,
                symbol_arg=symbol_arg,
                metadata_resolver=metadata_resolver,
            )
            return run_controlled_call(
                guard=call_context.guard,
                operation=registered_operation.key,
                symbol=call_context.symbol,
                metadata=call_context.metadata,
                call=lambda: function(*args, **kwargs),
                success_outcome=success_outcome,
                result_metadata_resolver=result_metadata_resolver,
            )

        return wrapper

    return decorator

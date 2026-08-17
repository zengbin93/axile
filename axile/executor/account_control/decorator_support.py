"""账户控制装饰器使用的参数解析与结果记录辅助函数."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

R = TypeVar("R")


@dataclass(frozen=True)
class ControlledCallContext:
    """保存一次受控调用在执行前解析出的上下文。"""

    guard: Any | None
    symbol: str | None
    metadata: dict[str, object]


def normalize_metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    """
    规范化事件元数据映射。

    Parameters
    ----------
    value : Mapping[str, object] | None
        原始元数据。

    Returns
    -------
    dict[str, object]
        标准化后的元数据字典。
    """
    if value is None:
        return {}
    return {str(key): item for key, item in value.items()}


def resolve_controlled_call_context(
    *,
    bound_arguments: inspect.BoundArguments,
    owner: object | None,
    symbol_arg: str | None,
    metadata_resolver: Callable[[inspect.BoundArguments], Mapping[str, object] | None] | None,
) -> ControlledCallContext:
    """
    解析一次受控调用在执行前需要的 guard、symbol 和 metadata。

    Parameters
    ----------
    bound_arguments : inspect.BoundArguments
        当前调用已绑定的参数。
    owner : object | None
        当前方法宿主；通常是 ``self``。
    symbol_arg : str | None
        用于读取交易标的参数的参数名。
    metadata_resolver : Callable[[inspect.BoundArguments], Mapping[str, object] | None] | None
        从参数中提取事件元数据的解析函数。

    Returns
    -------
    ControlledCallContext
        已解析好的受控调用上下文。
    """
    # 装饰器默认约定“第一个位置参数是宿主对象”，这样同步和异步包装都能共用同一套解析逻辑。
    return ControlledCallContext(
        guard=_resolve_guard_from_owner(owner),
        symbol=_resolve_value_from_arguments(bound_arguments, arg_name=symbol_arg),
        metadata=normalize_metadata(None if metadata_resolver is None else metadata_resolver(bound_arguments)),
    )


def record_controlled_success(
    *,
    attempt: Any,
    result: R,
    metadata: dict[str, object],
    success_outcome: str | Callable[[R], str],
    result_metadata_resolver: Callable[[R], Mapping[str, object] | None] | None,
) -> None:
    """
    记录一次受控调用的成功结果。

    Parameters
    ----------
    attempt : Any
        `guard.begin_operation()` 返回的尝试对象。
    result : R
        下游调用的返回值。
    metadata : dict[str, object]
        调用前已解析出的基础元数据。
    success_outcome : str | Callable[[R], str]
        成功时要写入的 outcome 或其解析函数。
    result_metadata_resolver : Callable[[R], Mapping[str, object] | None] | None
        基于返回值补充事件元数据的解析函数。
    """
    # success metadata 允许依赖返回值，避免在真正成功前把猜测性的结果写进事件。
    resolved_metadata = _resolve_result_metadata(
        base_metadata=metadata,
        result=result,
        result_metadata_resolver=result_metadata_resolver,
    )
    resolved_outcome = _resolve_success_outcome(success_outcome, result)
    attempt.record_outcome(resolved_outcome, metadata=resolved_metadata)


def record_controlled_failure(*, attempt: Any, metadata: dict[str, object]) -> None:
    """
    记录一次受控调用在下游执行阶段的失败结果。

    Parameters
    ----------
    attempt : Any
        `guard.begin_operation()` 返回的尝试对象。
    metadata : dict[str, object]
        需要随失败结果一起写入的元数据。
    """
    attempt.record_outcome("downstream_error", metadata=metadata)


def _normalize_optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _resolve_guard_from_owner(owner: object | None) -> Any | None:
    if owner is None:
        return None
    # 优先走显式 getter，给执行器一层机会决定当前 guard 的真实来源。
    guard_getter = getattr(owner, "get_account_control_guard", None)
    if callable(guard_getter):
        return guard_getter()
    return getattr(owner, "_account_control_guard", None)


def _resolve_value_from_arguments(
    bound_arguments: inspect.BoundArguments,
    *,
    arg_name: str | None,
) -> str | None:
    if arg_name is None:
        return None
    return _normalize_optional_string(bound_arguments.arguments.get(arg_name))


def _resolve_success_outcome(
    success_outcome: str | Callable[[R], str],
    result: R,
) -> str:
    if isinstance(success_outcome, str):
        return success_outcome
    return str(success_outcome(result))


def _resolve_result_metadata(
    *,
    base_metadata: dict[str, object],
    result: R,
    result_metadata_resolver: Callable[[R], Mapping[str, object] | None] | None,
) -> dict[str, object]:
    if result_metadata_resolver is None:
        return base_metadata
    return {
        **base_metadata,
        **normalize_metadata(result_metadata_resolver(result)),
    }

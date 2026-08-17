"""账户控制装饰器使用的 operation 注册辅助函数."""

from __future__ import annotations

from axile.executor.account_control.registry import (
    RegisteredAccountControlOperation,
    get_default_account_control_registry,
)


def build_registered_operation(
    operation: str,
    *,
    groups: tuple[str, ...],
) -> RegisteredAccountControlOperation:
    """
    构造并校验受控操作的注册描述。

    Parameters
    ----------
    operation : str
        需要注册的操作键。
    groups : tuple[str, ...]
        当前操作所属的共享节流组。

    Returns
    -------
    RegisteredAccountControlOperation
        标准化后的注册描述。
    """
    normalized_key = operation.strip()
    if not normalized_key:
        raise ValueError("operation key 不能为空")
    return RegisteredAccountControlOperation(
        key=normalized_key,
        groups=frozenset(group.strip() for group in groups),
    )


def register_or_validate_operation(
    operation: RegisteredAccountControlOperation,
) -> RegisteredAccountControlOperation:
    """
    在默认注册表中登记操作，或校验冻结状态下的定义一致性。

    Parameters
    ----------
    operation : RegisteredAccountControlOperation
        需要登记或校验的操作定义。

    Returns
    -------
    RegisteredAccountControlOperation
        生效的操作定义。
    """
    registry = get_default_account_control_registry()
    for group_key in operation.groups:
        # 先校验 group 是否存在，避免拼写错误在 registry freeze 之后才暴露。
        if registry.get_group(group_key) is None:
            raise ValueError(f"未注册的 group key: {group_key}")

    if registry.is_frozen:
        existing = registry.get_operation(operation.key)
        if existing is None:
            return operation
        if existing != operation:
            raise ValueError(f"operation key `{operation.key}` definition conflict")
        return existing

    return registry.register_operation(
        operation.key,
        groups=operation.groups,
    )


def register_operation_bootstrap(operation: RegisteredAccountControlOperation) -> None:
    """
    在默认注册表 bootstrap 阶段补注册操作。

    Parameters
    ----------
    operation : RegisteredAccountControlOperation
        需要补注册的操作定义。
    """
    registry = get_default_account_control_registry()
    # 装饰器可能在不同导入顺序下多次触发 bootstrap，这里要求补注册过程天然幂等。
    if registry.is_frozen:
        existing = registry.get_operation(operation.key)
        if existing is None:
            return
        if existing != operation:
            raise ValueError(f"operation key `{operation.key}` definition conflict")
        return
    register_or_validate_operation(operation)

"""账户控制测试辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast


def _normalize_rule_override(value: object) -> dict[str, object]:
    """将测试里使用的简写规则值转为显式 override 结构。"""
    if isinstance(value, Mapping):
        return dict(cast("Mapping[str, object]", value))
    return {"limit": cast("object", value)}


def _normalize_scope_override(scope: Mapping[str, object]) -> dict[str, object]:
    """将账户级或标的级 scope 规则映射转为显式结构。"""
    return {
        rule_key: _normalize_rule_override(rule_value)
        for rule_key, rule_value in cast("Mapping[str, object]", scope).items()
    }


def _normalize_operation_override(operation: object) -> dict[str, object]:
    """将操作级 override 转为显式 `account` / `symbol` 结构。"""
    if not isinstance(operation, Mapping):
        raise TypeError("operation override 必须是映射类型")

    operation_mapping = cast("Mapping[str, object]", operation)
    if "account" in operation_mapping or "symbol" in operation_mapping:
        normalized: dict[str, object] = {}
        if "account" in operation_mapping and operation_mapping["account"] is not None:
            normalized["account"] = _normalize_scope_override(
                cast("Mapping[str, object]", operation_mapping["account"])
            )
        if "symbol" in operation_mapping and operation_mapping["symbol"] is not None:
            normalized["symbol"] = _normalize_scope_override(cast("Mapping[str, object]", operation_mapping["symbol"]))
        return normalized

    return {"account": _normalize_scope_override(operation_mapping)}


def normalize_account_control_override(override: Mapping[str, object]) -> dict[str, object]:
    """将测试用旧简写 override 结构归一化为当前模型可接受的输入。"""
    normalized_override = dict(override)
    operations = normalized_override.pop("operations", None)

    if operations is None:
        operations = {
            key: normalized_override.pop(key) for key in list(normalized_override) if key not in {"timezone", "groups"}
        }

    if operations is not None:
        normalized_override["operations"] = {
            operation_key: _normalize_operation_override(operation_value)
            for operation_key, operation_value in cast("Mapping[str, object]", operations).items()
        }

    if "groups" in normalized_override and normalized_override["groups"] is not None:
        normalized_override["groups"] = {
            group_key: _normalize_scope_override(cast("Mapping[str, object]", group_value))
            for group_key, group_value in cast("Mapping[str, object]", normalized_override["groups"]).items()
        }

    return normalized_override

"""算法注册表相关测试。"""

from typing import Any, cast

import pytest

from axile.executor.algorithms.core.base import get_algorithm_metadata, register_algorithm


def test_register_algorithm_no_longer_accepts_symbol_level() -> None:
    """`symbol_level` 参数应当已经移除。"""
    register_algorithm_any = cast("Any", register_algorithm)
    with pytest.raises(TypeError):
        register_algorithm_any("TEST-ALGO", symbol_level=True)


def _noop_algorithm(executor: Any, algorithm_input: Any) -> Any:
    """占位算法实现，仅用于注册元数据测试。"""
    return None


def test_slots_default_none_means_both_slots() -> None:
    """未声明 slots 时应为 ``None``，表示主交易与清仓两槽通用。"""
    register_algorithm("TEST-SLOTS-DEFAULT")(_noop_algorithm)
    meta = get_algorithm_metadata("TEST-SLOTS-DEFAULT")
    assert meta.slots is None


def test_slots_empty_list_is_not_none() -> None:
    """空列表 ``[]`` 表示两槽都不适用，且不塌缩为 ``None``。"""
    register_algorithm("TEST-SLOTS-EMPTY", slots=[])(_noop_algorithm)
    meta = get_algorithm_metadata("TEST-SLOTS-EMPTY")
    assert meta.slots == frozenset()
    assert meta.slots is not None


def test_slots_explicit_values_are_frozen() -> None:
    """显式声明的槽位应转成 frozenset 保存。"""
    register_algorithm("TEST-SLOTS-EMPTY-ONLY", slots=["empty"])(_noop_algorithm)
    meta = get_algorithm_metadata("TEST-SLOTS-EMPTY-ONLY")
    assert meta.slots == frozenset({"empty"})


def test_builtin_slots_restrictions() -> None:
    """内置算法的槽位声明符合约定。"""
    assert get_algorithm_metadata("CTP_OPTION_EXERCISE").slots == frozenset()
    # 通用算法保持 None（两槽通用）。
    assert get_algorithm_metadata("SINGLE-MAKER").slots is None

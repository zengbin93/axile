"""账户控制注册表测试。"""

from __future__ import annotations

import pytest

from axile.executor.account_control.registry import (
    AccountControlRegistry,
)


def test_registry_freeze_blocks_new_operation_registration() -> None:
    registry = AccountControlRegistry()
    registry.register_operation("query_account")
    registry.freeze()

    with pytest.raises(RuntimeError, match="frozen"):
        registry.register_operation("query_positions")


def test_registry_freeze_blocks_new_group_registration() -> None:
    registry = AccountControlRegistry()
    registry.register_group("ctp_td_global")
    registry.freeze()

    with pytest.raises(RuntimeError, match="frozen"):
        registry.register_group("external_rest_global")


def test_register_operation_allows_identical_reuse_but_rejects_conflicts() -> None:
    registry = AccountControlRegistry()
    first = registry.register_operation(
        "place_order",
        groups={"trade_global"},
    )
    second = registry.register_operation(
        "place_order",
        groups={"trade_global"},
    )

    assert first is second
    assert first.groups == frozenset({"trade_global"})

    with pytest.raises(ValueError, match="conflict"):
        registry.register_operation(
            "place_order",
            groups={"other_group"},
        )


def test_register_group_allows_identical_reuse_after_key_normalization() -> None:
    registry = AccountControlRegistry()
    first = registry.register_group("ctp_td_global")
    second = registry.register_group(" ctp_td_global ")

    assert first is second

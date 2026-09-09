"""F17 单笔数量限制：纯函数回归，不导入 openctp。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from axile.executor.order_volume_limits import (
    effective_max_order_volume,
    ensure_order_volume_allowed,
    split_order_volumes,
)
from axile.executor.models.unified_order import OrderType


def test_F17_effective_max_prefers_stricter_user_limit() -> None:
    instrument = SimpleNamespace(MaxLimitOrderVolume=10, MinLimitOrderVolume=1)
    minimum, maximum = effective_max_order_volume(
        instrument, OrderType.LIMIT, {"max_single_order_size": 2}
    )
    assert minimum == 1
    assert maximum == 2


def test_F17_contract_max_applies_without_user_limit() -> None:
    instrument = SimpleNamespace(MaxLimitOrderVolume=10, MinLimitOrderVolume=1)
    _minimum, maximum = effective_max_order_volume(instrument, OrderType.LIMIT, {})
    assert maximum == 10


def test_F17_market_uses_market_fields() -> None:
    instrument = SimpleNamespace(
        MaxLimitOrderVolume=10,
        MaxMarketOrderVolume=3,
        MinMarketOrderVolume=1,
    )
    _minimum, maximum = effective_max_order_volume(instrument, OrderType.MARKET, None)
    assert maximum == 3


def test_F17_ensure_blocks_over_limit_before_api() -> None:
    instrument = SimpleNamespace(MaxLimitOrderVolume=10, MinLimitOrderVolume=1)
    with pytest.raises(ValueError, match="超过单笔上限 2"):
        ensure_order_volume_allowed(
            50,
            instrument=instrument,
            order_type=OrderType.LIMIT,
            trade_rule={"max_single_order_size": 2},
        )


def test_F17_ensure_allows_boundary() -> None:
    instrument = SimpleNamespace(MaxLimitOrderVolume=10, MinLimitOrderVolume=1)
    assert (
        ensure_order_volume_allowed(
            2,
            instrument=instrument,
            order_type=OrderType.LIMIT,
            trade_rule={"max_single_order_size": 2},
        )
        == 2
    )


def test_F17_split_respects_user_cap_without_padding_tail() -> None:
    assert split_order_volumes(50, 2) == [2] * 25
    assert split_order_volumes(5, 2, min_size=2) == [2, 2]
    assert sum(split_order_volumes(5, 2, min_size=2)) == 4


def test_F17_user_max_higher_than_contract_uses_contract() -> None:
    instrument = SimpleNamespace(MaxLimitOrderVolume=10, MinLimitOrderVolume=1)
    _minimum, maximum = effective_max_order_volume(
        instrument, OrderType.LIMIT, {"max_single_order_size": 20}
    )
    assert maximum == 10

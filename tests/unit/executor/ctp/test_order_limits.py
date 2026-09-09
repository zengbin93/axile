"""F17 单笔数量限制：纯函数回归，不导入 openctp。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from axile.executor.models.unified_order import OrderType
from axile.executor.order_volume_limits import (
    effective_max_order_volume,
    ensure_order_volume_allowed,
    split_order_volumes,
)


def test_F17_effective_max_prefers_stricter_user_limit() -> None:
    instrument = SimpleNamespace(MaxLimitOrderVolume=10, MinLimitOrderVolume=1)
    minimum, maximum = effective_max_order_volume(instrument, OrderType.LIMIT, {"max_single_order_size": 2})
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
    _minimum, maximum = effective_max_order_volume(instrument, OrderType.LIMIT, {"max_single_order_size": 20})
    assert maximum == 10


@pytest.mark.parametrize(
    ("total", "minimum", "maximum", "expected"),
    [(12, 3, 10, [9, 3]), (5, 3, 4, [4]), (2, 3, 10, []), (20, 3, 10, [10, 10]), (12, 3, None, [12])],
)
def test_split_minimum_and_maximum(total, minimum, maximum, expected):
    assert split_order_volumes(total, maximum, min_size=minimum) == expected


def test_split_maximizes_legal_volume_and_minimizes_order_count():
    for minimum in range(1, 8):
        for maximum in range(minimum, 12):
            for total in range(1, 50):
                slices = split_order_volumes(total, maximum, min_size=minimum)
                possible = [
                    (min(total, count * maximum), count) for count in range(total + 1) if count * minimum <= total
                ]
                best_volume = max(volume for volume, _ in possible)
                best_count = min(count for volume, count in possible if volume == best_volume)
                assert sum(slices) == best_volume
                assert len(slices) == best_count
                assert all(minimum <= volume <= maximum for volume in slices)


def test_conflicting_bounds_fail():
    with pytest.raises(ValueError):
        split_order_volumes(12, 2, min_size=3)
    with pytest.raises(ValueError):
        effective_max_order_volume(
            SimpleNamespace(MinLimitOrderVolume=3), OrderType.LIMIT, {"max_single_order_size": 2}
        )

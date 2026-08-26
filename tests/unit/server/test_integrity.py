"""在位性计数与前端 rebalancePlan 口径对齐。"""

from axile.server.integrity import REBALANCE_THRESHOLD, count_off_symbols


def test_rebalance_threshold_matches_frontend_constant() -> None:
    """与 ``axile/ui/src/lib/derive.ts`` 的 ``REBALANCE_THRESHOLD`` 锁死为 0.5。"""
    assert REBALANCE_THRESHOLD == 0.5


def test_count_off_symbols_matches_screenshot_book() -> None:
    """现持 RM611 空头 + 4 个目标 → 5 只待调整。"""
    positions = [{"symbol": "RM611", "market_value": 46000, "direction": "空头"}]
    target = {"TA701": -0.07, "c2611": 0.03, "m2701": -0.06, "rb2610": 0.12}
    assert count_off_symbols(positions, target, 993_114.59) == 5


def test_count_off_symbols_aligned_within_threshold() -> None:
    """当前权重与目标相差不超过 0.5 个百分点视为到位。"""
    positions = [{"symbol": "rb2610", "market_value": 120, "direction": "多头"}]
    assert count_off_symbols(positions, {"rb2610": 0.12}, 1000) == 0


def test_count_off_symbols_ignores_both_zero() -> None:
    positions = [{"symbol": "ghost", "market_value": 0, "direction": "多头"}]
    assert count_off_symbols(positions, {"ghost": 0.0}, 1000) == 0


def test_count_off_symbols_short_direction_english() -> None:
    positions = [{"symbol": "RM611", "market_value": 50_000, "direction": "short"}]
    assert count_off_symbols(positions, {}, 100_000) == 1

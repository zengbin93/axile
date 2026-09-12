"""三种真实算法入口的结果状态与恢复异常回归。"""

from unittest.mock import MagicMock

import pytest

from axile.executor.algorithms.core.base import AlgorithmInput
from axile.executor.algorithms.defaults.pov import impl as pov
from axile.executor.algorithms.defaults.single_maker import impl as maker
from axile.executor.algorithms.defaults.twap import impl as twap
from axile.executor.constants.order_status import OrderStatus
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_order import OrderDirection, OrderType, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


class RecoveryRequired(RuntimeError):
    requires_session_recovery = True


@pytest.mark.parametrize("module", [maker, twap, pov], ids=["maker", "twap", "pov"])
@pytest.mark.parametrize(
    "case, expected",
    [
        ("reject", ExecutionStatus.FAILED),
        ("timeout", ExecutionStatus.FAILED),
        ("partial", ExecutionStatus.PARTIAL),
        ("unknown_cancel", ExecutionStatus.FAILED),
        ("filled", ExecutionStatus.SUCCEEDED),
        ("noop", ExecutionStatus.NOOP),
        ("recovery", None),
    ],
)
def test_algorithm_outcome(monkeypatch, module, case, expected):
    executor = MagicMock()
    executor.symbol = "rb2610"
    assets = UnifiedAccountAssets(available_cash=10000, total_asset=10000, market_value=0, positions=[])
    executor.get_account_assets.return_value = assets
    volume = [2 if case == "noop" else 0]
    executor.get_current_volume.side_effect = lambda _: volume[0]
    executor.get_market_data.return_value = UnifiedPriceData(
        symbol="rb2610",
        last_price=100,
        bid_price=99,
        ask_price=101,
        bid_volume=1,
        ask_volume=1,
        volume=10,
        turnover=1000,
        timestamp=1,
        update_time="",
    )
    tracker = MagicMock()
    orders = []
    tracker.get_all_orders.side_effect = lambda: orders
    tracker.get_all_trades.return_value = []
    monkeypatch.setattr(module, "setup_order_tracker", lambda *args: tracker)
    monkeypatch.setattr(module, "teardown_order_tracker", lambda *args: None)

    def submit(*args, **kwargs):
        if case == "reject":
            raise RuntimeError("synthetic reject")
        if case == "recovery":
            raise RecoveryRequired("rebuild session")
        volume[0] = {"filled": 2, "partial": 1}.get(case, 0)
        status = {"filled": OrderStatus.FILLED, "partial": OrderStatus.CANCELED, "timeout": OrderStatus.CANCELED}.get(
            case, OrderStatus.PENDING
        )
        order = UnifiedOrder(
            order_id="1",
            symbol="rb2610",
            direction=OrderDirection.BUY,
            order_type=OrderType.LIMIT,
            volume=2,
            price=101,
            status=status,
            filled_volume=volume[0],
        )
        orders.append(order)
        return order

    def split_submit(*args, **kwargs):
        order = submit(*args, **kwargs)
        return [order] if order is not None else []

    monkeypatch.setattr(module, "submit_and_track_split_orders", split_submit)
    if module is maker:
        entry, params = maker.single_maker_callback, maker.SingleMakerParams(max_wait_seconds=1)
    else:
        now = [0.0]
        clock = MagicMock()
        clock.time.side_effect = lambda: now[0]
        executor.sleep_or_terminate.side_effect = lambda duration: now.__setitem__(0, now[0] + duration)
        monkeypatch.setattr(module, "get_default_clock", lambda: clock)
        monkeypatch.setattr(
            module, "cancel_pending_orders_via_query", lambda _: ["1"] if case == "unknown_cancel" else []
        )
        if module is twap:
            entry, params = twap.twap, twap.TwapParams(slices=1, total_duration=1, max_wait_seconds=1)
        else:
            entry, params = (
                pov.pov,
                pov.PovParams(max_duration=1, interval_seconds=1, complete_on_timeout=True, max_wait_seconds=1),
            )
    input_data = AlgorithmInput(symbol="rb2610", target_volume=2, trade_rule={}, params=params)
    if case == "recovery":
        with pytest.raises(RecoveryRequired):
            entry(executor, input_data)
        return
    result = entry(executor, input_data)
    assert result.status == expected
    assert result.model_dump(mode="json")["status"] == expected.value
    if expected in {ExecutionStatus.FAILED, ExecutionStatus.PARTIAL}:
        assert result.error
        assert result.memory["remaining_volume"] == 2 - volume[0]
    if case == "reject":
        assert "synthetic reject" in result.error
    if case == "noop":
        assert not orders

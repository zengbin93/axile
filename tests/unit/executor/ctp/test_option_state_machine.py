"""``OptionActionTracker`` 状态机单元测试.

覆盖设计文档 §5.5.3 中的 7 种状态转移路径:

- Pending → Submitted → Executed
- Pending → Submitted → Abandoned
- Pending → Submitted → Cancelling → Cancelled
- Pending → Submitted → Cancelling → Failed（撤销被拒）
- Pending → Submitted → Failed（交易所拒绝）
- Pending → Failed（前置机拒绝）
- 终态不可逆转移
"""

from __future__ import annotations

import pytest

from axile.executor.ctp.core.option_action import (
    OptionActionStatus,
    OptionActionTracker,
    OptionActionType,
    operation_key,
)


@pytest.fixture
def tracker() -> OptionActionTracker:
    """每个用例独立的 tracker。"""
    return OptionActionTracker()


def _register_default(tracker: OptionActionTracker, ref: str = "100") -> None:
    """登记一条默认行权指令到 Pending。"""
    tracker.register(
        order_ref=ref,
        instrument_id="m2510-C-3100",
        action=OptionActionType.EXERCISE,
        volume=5,
    )


class TestRegister:
    def test_register_creates_pending_record(self, tracker: OptionActionTracker) -> None:
        record = tracker.register(
            order_ref="1",
            instrument_id="m2510-C-3100",
            action=OptionActionType.EXERCISE,
            volume=3,
        )
        assert record.status == OptionActionStatus.PENDING
        assert record.action == OptionActionType.EXERCISE
        assert record.volume == 3

    def test_duplicate_order_ref_rejected(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        with pytest.raises(ValueError, match="重复行权指令"):
            _register_default(tracker)


class TestHappyPath:
    def test_pending_submitted_executed(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.EXECUTED)
        assert tracker.is_terminal("100")
        assert tracker.get("100").status == OptionActionStatus.EXECUTED

    def test_pending_submitted_abandoned(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.ABANDONED)
        assert tracker.is_terminal("100")
        assert tracker.get("100").status == OptionActionStatus.ABANDONED


class TestCancellation:
    def test_pending_submitted_cancelling_cancelled(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.CANCELLING)
        tracker.transition("100", OptionActionStatus.CANCELLED)
        assert tracker.is_terminal("100")

    def test_cancelling_can_fall_to_failed(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.CANCELLING)
        tracker.transition("100", OptionActionStatus.FAILED, error_msg="撤销被交易所拒")
        assert tracker.get("100").status == OptionActionStatus.FAILED
        assert tracker.get("100").error_msg == "撤销被交易所拒"


class TestFailurePaths:
    def test_pending_to_failed_when_front_rejects(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition(
            "100",
            OptionActionStatus.FAILED,
            error_id=999,
            error_msg="前置机拒绝",
            error_source="front",
        )
        assert tracker.is_terminal("100")
        record = tracker.get("100")
        assert record.error_id == 999
        assert record.error_source == "front"

    def test_submitted_to_failed_when_exchange_rejects(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition(
            "100",
            OptionActionStatus.FAILED,
            error_id=2000,
            error_msg="交易所拒绝",
            error_source="exchange",
        )
        record = tracker.get("100")
        assert record.error_source == "exchange"


class TestIllegalTransitions:
    def test_terminal_status_cannot_transit(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.EXECUTED)
        # 终态不能再转
        with pytest.raises(ValueError, match="非法状态转移"):
            tracker.transition("100", OptionActionStatus.CANCELLED)

    def test_pending_cannot_jump_to_executed(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        with pytest.raises(ValueError, match="非法状态转移"):
            tracker.transition("100", OptionActionStatus.EXECUTED)

    def test_unknown_order_ref_raises(self, tracker: OptionActionTracker) -> None:
        with pytest.raises(KeyError):
            tracker.transition("nonexistent", OptionActionStatus.SUBMITTED)


class TestActiveListing:
    def test_list_active_excludes_terminal(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker, ref="100")
        tracker.register(order_ref="200", instrument_id="x", action=OptionActionType.ABANDON, volume=1)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.EXECUTED)

        active = tracker.list_active()
        assert {r.order_ref for r in active} == {"200"}

    def test_all_records_keeps_history(self, tracker: OptionActionTracker) -> None:
        _register_default(tracker)
        tracker.transition("100", OptionActionStatus.SUBMITTED)
        tracker.transition("100", OptionActionStatus.EXECUTED)
        all_records = tracker.all_records()
        assert len(all_records) == 1


class TestOperationKey:
    def test_operation_keys(self) -> None:
        assert operation_key(OptionActionType.EXERCISE) == "option_exercise"
        assert operation_key(OptionActionType.ABANDON) == "option_abandon"
        assert operation_key(OptionActionType.SELF_CLOSE) == "option_self_close"

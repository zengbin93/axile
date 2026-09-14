"""风控中文提示与触发快照回归测试。"""

import json
from datetime import datetime
from unittest.mock import Mock

import pytest
from loguru import logger

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.ctp_operations import CTP_TRADER_API_OPERATIONS
from axile.executor.account_control.diagnostics import OPERATION_LABELS, operation_label
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.models import AccountControlPolicy
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from tests.unit.executor.test_account_control_guard import _AdvancingClock


def make_guard(rule, *, scope="account", timezone="Asia/Shanghai", clock=None):
    policy = AccountControlPolicy.model_validate({"timezone": timezone, "operations": {"place_order": {scope: rule}}})
    return AccountControlGuard(
        account_id=12,
        execution_id="exec-diagnostics",
        channel=TradeChannel("external"),
        policy=policy,
        baseline=AccountControlCounterSnapshot(),
        clock=(lambda: datetime(2026, 9, 14, 21, 45, 13)) if clock is None else None,
        wait_clock=clock,
    )


@pytest.mark.parametrize("scope", ["account", "symbol"])
@pytest.mark.parametrize("rule,label", [("per_day", "每日下单次数"), ("per_minute", "每分钟下单次数")])
def test_block_snapshot_matches_error(scope, rule, label):
    guard = make_guard({rule: {"limit": 1, "on_trigger": "block"}}, scope=scope)
    guard.begin_operation("place_order", symbol="zn2611")
    submit = Mock()
    with pytest.raises(AccountControlBlockedError) as caught:
        guard.begin_operation(
            "place_order", symbol="zn2611", metadata={"source": "test", "account_control_hit": "forged"}
        )
        submit()
    submit.assert_not_called()
    detail = caught.value.details
    assert detail.current_value == detail.limit == 1
    assert detail.scope_type == scope
    assert detail.scope_symbol == ("zn2611" if scope == "symbol" else None)
    assert label in str(caught.value)
    assert rule not in str(caught.value)
    _, events = guard.flush_records()
    assert events[-1].counted is False
    assert events[-1].metadata == {
        "source": "test",
        "account_control_hit": json.loads(json.dumps(detail.to_metadata())),
    }


@pytest.mark.parametrize("rule", ["per_day", "per_minute"])
def test_zero_limit_has_no_retry_promise(rule):
    guard = make_guard({rule: {"limit": 0, "on_trigger": "block"}})
    with pytest.raises(AccountControlBlockedError) as caught:
        guard.begin_operation("place_order")
    assert caught.value.details.retry_after_ms is None
    assert "配置上限为 0" in str(caught.value)
    assert "重置时间" not in str(caught.value)
    assert "None" not in str(caught.value)


def test_actual_count_above_limit_and_local_date():
    guard = make_guard({"per_day": {"limit": 5, "on_trigger": "block"}}, timezone="America/New_York")
    for _ in range(3):
        guard.begin_operation("place_order")
    guard.policy.operations["place_order"].account.per_day.limit = 2
    with pytest.raises(AccountControlBlockedError) as caught:
        guard.begin_operation("place_order")
    detail = caught.value.details
    assert detail.current_value == 3
    assert detail.limit == 2
    assert detail.window_start == "2026-09-14T00:00:00-04:00"
    assert detail.window_end == "2026-09-15T00:00:00-04:00"


def test_wait_deduplication_and_reserved_metadata():
    clock = _AdvancingClock(datetime.fromisoformat("2026-09-14T21:45:13+08:00"))
    guard = make_guard({"min_interval_ms": {"limit": 500, "on_trigger": "wait"}}, clock=clock)
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    try:
        guard.begin_operation("place_order")
        clock.sleep(0.12)
        attempt = guard.begin_operation("place_order", metadata={"account_control_hit": "forged"})
        attempt.record_outcome("submitted", metadata={"account_control_wait_hits": "forged", "order_id": "1"})
    finally:
        logger.remove(sink)
    _, events = guard.flush_records()
    hits = events[-1].metadata["account_control_wait_hits"]
    assert len(hits) == 1
    assert hits[0]["current_value"] == 120
    assert hits[0]["retry_after_ms"] == 380
    assert hits[0]["window_start"] is None
    assert events[-1].metadata["order_id"] == "1"
    assert "account_control_hit" not in events[-1].metadata
    assert sum("账户风控等待额度" in message for message in messages) == 1
    assert guard.current_wait_hits() == ("place_order.min_interval_ms",)


def test_interval_block_and_legacy_exception():
    guard = make_guard({"min_interval_ms": {"limit": 500, "on_trigger": "block"}})
    guard.begin_operation("place_order")
    with pytest.raises(AccountControlBlockedError) as caught:
        guard.begin_operation("place_order")
    assert "已间隔 0 毫秒，要求至少 500 毫秒，还需等待 500 毫秒" in str(caught.value)
    error = AccountControlBlockedError(
        "其他风控", account_id=None, execution_id=None, channel=TradeChannel("external"), operation="place_order"
    )
    assert error.details is None


def test_operation_labels_cover_registry():
    assert CTP_TRADER_API_OPERATIONS | {"place_order", "cancel_order", "query_order", "query_trades"} <= set(
        OPERATION_LABELS
    )
    assert operation_label("plugin_custom") == "自定义操作（plugin_custom）"


def test_wait_then_block_uses_final_snapshot():
    clock = _AdvancingClock(datetime.fromisoformat("2026-09-14T21:45:13+08:00"))
    guard = make_guard({"min_interval_ms": {"limit": 500, "on_trigger": "wait"}}, clock=clock)
    guard.begin_operation("place_order")
    original_sleep = clock.sleep

    def exhaust_daily_quota(seconds):
        original_sleep(seconds)
        from axile.executor.account_control.models import AccountControlRule

        guard.policy.operations["place_order"].account.per_day = AccountControlRule(limit=1, on_trigger="block")

    guard._sleep = exhaust_daily_quota
    with pytest.raises(AccountControlBlockedError) as caught:
        guard.begin_operation("place_order")
    _, events = guard.flush_records()
    assert caught.value.details.rule_kind == "per_day"
    assert caught.value.details.evaluated_at == "2026-09-14T21:45:13.100000+08:00"
    assert events[-1].metadata["account_control_wait_hits"][0]["rule_kind"] == "min_interval_ms"
    assert events[-1].metadata["account_control_hit"] == caught.value.details.to_metadata()


def test_daily_window_rollover():
    clock = _AdvancingClock(datetime.fromisoformat("2026-09-14T23:59:59.800000+08:00"))
    guard = make_guard({"per_day": {"limit": 1, "on_trigger": "wait"}}, clock=clock)
    guard.begin_operation("place_order")
    guard.begin_operation("place_order")
    _, events = guard.flush_records()
    assert events[-1].control_date == "2026-09-15"
    hit = events[-1].metadata["account_control_wait_hits"][0]
    assert hit["window_end"] == "2026-09-15T00:00:00+08:00"
    assert hit["retry_after_ms"] == 200


def test_block_still_applies_in_last_submillisecond_of_window():
    guard = make_guard({"per_minute": {"limit": 0, "on_trigger": "block"}})
    guard._clock = lambda: datetime(2026, 9, 14, 21, 45, 59, 999999)
    with pytest.raises(AccountControlBlockedError):
        guard.begin_operation("place_order")


def test_longest_wait_detail_is_selected():
    clock = _AdvancingClock(datetime.fromisoformat("2026-09-14T21:45:59.800000+08:00"))
    guard = make_guard(
        {
            "per_minute": {"limit": 1, "on_trigger": "wait"},
            "min_interval_ms": {"limit": 500, "on_trigger": "wait"},
        },
        clock=clock,
    )
    guard.begin_operation("place_order")
    guard.begin_operation("place_order")
    _, events = guard.flush_records()
    assert events[-1].metadata["account_control_wait_hits"][0]["rule_kind"] == "min_interval_ms"
    assert events[-1].metadata["account_control_wait_hits"][0]["retry_after_ms"] == 500

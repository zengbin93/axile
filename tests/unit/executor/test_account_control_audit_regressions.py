"""SKZ-737 safety invariants; strict xfails document unfixed audit findings."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control import registry as registry_module
from axile.executor.account_control.decorator_registry import register_or_validate_operation
from axile.executor.account_control.decorators import run_controlled_async_call, run_controlled_call
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.models import AccountControlOverride, AccountControlPolicy
from axile.executor.account_control.presets import (
    ensure_account_control_preset_compatible,
    resolve_account_control_policy,
)
from axile.executor.account_control.registry import AccountControlRegistry, RegisteredAccountControlOperation
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot


class AuditClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 9, 10)

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def build_guard(clock: AuditClock, policy: AccountControlPolicy | None = None) -> AccountControlGuard:
    return AccountControlGuard(
        account_id=7,
        execution_id="skz-737-audit",
        channel=TradeChannel.CTP,
        policy=policy if policy is not None else resolve_account_control_policy("ctp"),
        baseline=AccountControlCounterSnapshot(),
        clock=lambda: clock.now,
        sleep=clock.sleep,
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="SKZ-737 R4: async quota wait blocks the event loop")
def test_async_quota_wait_yields_to_ready_callbacks() -> None:
    async def scenario() -> None:
        clock = AuditClock()
        guard = build_guard(clock)
        guard.begin_operation("query_account")
        heartbeat_seen = []
        asyncio.get_running_loop().call_soon(heartbeat_seen.append, True)

        async def downstream() -> bool:
            return bool(heartbeat_seen)

        heartbeat_before_send = await run_controlled_async_call(
            guard=guard, operation="query_positions", call=downstream
        )
        await asyncio.sleep(0)
        assert heartbeat_seen
        assert heartbeat_before_send

    asyncio.run(scenario())


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="SKZ-737 R5: unknown operation fails open")
def test_unknown_operation_is_rejected_before_downstream() -> None:
    calls = []
    guard = build_guard(AuditClock())
    try:
        run_controlled_call(guard=guard, operation="query_acount_typo", call=lambda: calls.append(True))
    except (ValueError, AccountControlBlockedError):
        pass
    assert calls == []


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="SKZ-737 R5: frozen registry silently accepts unknown declaration"
)
def test_frozen_registry_rejects_late_unknown_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = AccountControlRegistry()
    registry.freeze()
    monkeypatch.setattr(registry_module, "_DEFAULT_REGISTRY", registry)
    rejected = False
    try:
        register_or_validate_operation(RegisteredAccountControlOperation(key="late_audit_operation"))
    except (ValueError, RuntimeError):
        rejected = True
    assert rejected


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="SKZ-737 R6: zero daily wait can never acquire quota")
def test_zero_daily_wait_blocks_instead_of_waiting_forever() -> None:
    clock = AuditClock()
    policy = AccountControlPolicy.model_validate(
        {
            "timezone": "Asia/Shanghai",
            "operations": {"place_order": {"account": {"per_day": {"limit": 0, "on_trigger": "wait"}}}},
        }
    )
    guard = build_guard(clock, policy)
    checkpoints = []

    class StopAudit(Exception):
        pass

    def checkpoint(symbol: str | None) -> None:
        checkpoints.append(symbol)
        if len(checkpoints) == 3:
            raise StopAudit

    guard.set_termination_checkpoint(checkpoint)
    blocked = False
    try:
        guard.begin_operation("place_order")
    except AccountControlBlockedError:
        blocked = True
    except StopAudit:
        pass
    assert blocked


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="SKZ-737 R7: cancellation leaves an allowed event pending"
)
def test_async_cancellation_records_terminal_outcome() -> None:
    guard = build_guard(AuditClock())

    async def cancelled() -> None:
        raise asyncio.CancelledError

    async def scenario() -> None:
        with pytest.raises(asyncio.CancelledError):
            await run_controlled_async_call(guard=guard, operation="query_account", call=cancelled)

    asyncio.run(scenario())
    _, events = guard.flush_records()
    assert events[0].outcome != "pending"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="SKZ-737 R8: reservation spacing is not send spacing")
def test_shared_group_spaces_actual_sends_after_local_preparation() -> None:
    clock = AuditClock()
    guard = build_guard(clock)
    sends = []

    def prepare_then_send() -> None:
        clock.sleep(2)
        sends.append(clock.now)

    run_controlled_call(guard=guard, operation="place_order", call=prepare_then_send)
    run_controlled_call(guard=guard, operation="query_account", call=lambda: sends.append(clock.now))
    assert (sends[1] - sends[0]).total_seconds() >= 1.5


def test_default_preset_on_ctp_does_not_attach_trader_group() -> None:
    ensure_account_control_preset_compatible("default", TradeChannel.CTP)
    clock = AuditClock()
    guard = build_guard(clock, resolve_account_control_policy("default"))
    guard.begin_operation("query_account")
    guard.begin_operation("query_positions")
    _, events = guard.flush_records()
    assert events[0].occurred_at_ms == events[1].occurred_at_ms


def test_default_trade_queries_are_recorded_without_a_finite_rule() -> None:
    policy = resolve_account_control_policy("default")
    scope = policy.operations["query_trades"].account
    assert scope.per_day is None
    assert scope.per_minute is None
    assert scope.min_interval_ms is None


def test_ctp_group_interval_can_be_lowered_to_one_millisecond() -> None:
    override = AccountControlOverride.model_validate({"groups": {"ctp_td_global": {"min_interval_ms": {"limit": 1}}}})
    policy = resolve_account_control_policy("ctp", override)
    assert policy.groups["ctp_td_global"].min_interval_ms.limit == 1


def test_independent_guards_reserve_the_same_account_budget() -> None:
    clock = AuditClock()
    policy = AccountControlPolicy.model_validate(
        {
            "timezone": "Asia/Shanghai",
            "operations": {"place_order": {"account": {"per_day": {"limit": 1, "on_trigger": "block"}}}},
        }
    )
    first = build_guard(clock, policy)
    second = build_guard(clock, policy)
    first.begin_operation("place_order")
    second.begin_operation("place_order")
    assert len(first.flush_records()[1]) + len(second.flush_records()[1]) == 2


@pytest.mark.parametrize(
    "operation,sdk_operation", [("query_account", "get_cash"), ("query_positions", "get_position")]
)
@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="SKZ-737 R1: GM asset queries bypass configured operation limits"
)
def test_gm_asset_queries_obey_zero_operation_quota(
    monkeypatch: pytest.MonkeyPatch, operation: str, sdk_operation: str
) -> None:
    from tests.unit.executor.test_gm_account_control import _build_executor, _build_guard, gm_api_bridge_module

    guard = _build_guard({operation: {"per_day": 0}})
    executor = _build_executor(guard)
    calls = []

    def get_position(**kwargs: object) -> list[object]:
        calls.append("get_position")
        return []

    def get_cash(**kwargs: object) -> dict[str, object]:
        calls.append("get_cash")
        return {}

    monkeypatch.setattr(gm_api_bridge_module, "get_position", get_position)
    monkeypatch.setattr(gm_api_bridge_module, "get_cash", get_cash)
    try:
        executor.get_account_assets()
    except AccountControlBlockedError:
        pass
    assert sdk_operation not in calls

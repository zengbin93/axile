"""SKZ-737 persistence risk reproductions against isolated in-memory SQLite."""

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select

from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.account_control.models import AccountControlBucketType
from axile.executor.account_control.presets import resolve_account_control_policy
from axile.executor.account_control.snapshot import AccountControlCounterSnapshot
from axile.server.account_control.store import AccountControlStore
from axile.server.db.models import AccountControlEvent
from tests.unit.server.test_account_control_store import _build_account, _session_scope


@pytest.mark.parametrize("invariant", ["counter", "outcome"])
@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="SKZ-737 R3: OR IGNORE drops updates to cumulative snapshots"
)
def test_incremental_flush_preserves_new_counts_and_outcomes(invariant: str) -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account()
            session.add(account)
            await session.commit()
            guard = AccountControlGuard(
                account_id=account.id,
                execution_id="skz-737-incremental",
                channel=account.trade_channel,
                policy=resolve_account_control_policy("default"),
                baseline=AccountControlCounterSnapshot(),
                clock=lambda: datetime(2026, 9, 9, 10),
            )
            store = AccountControlStore(session)
            attempt = guard.begin_operation("query_trades")
            deltas, events = guard.flush_records()
            await store.flush_execution_records(counter_deltas=deltas, events=events)
            attempt.record_outcome("fetched")
            guard.begin_operation("query_trades").record_outcome("fetched")
            deltas, events = guard.flush_records()
            await store.flush_execution_records(counter_deltas=deltas, events=events)
            if invariant == "counter":
                snapshot = await store.load_daily_counters(account.id, "2026-09-09")
                count = snapshot.get_count(
                    bucket_type=AccountControlBucketType.DAY,
                    bucket_start="2026-09-09T00:00:00",
                    operation="query_trades",
                )
                assert count == 2
            else:
                event = (
                    await session.execute(select(AccountControlEvent).where(AccountControlEvent.seq == 1))
                ).scalar_one()
                assert event.outcome == "fetched"

    asyncio.run(scenario())

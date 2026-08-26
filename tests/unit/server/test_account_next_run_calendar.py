"""账户下次实际执行时间的交易日历过滤测试。"""

from datetime import datetime
from types import SimpleNamespace

from axile.common.trade_channel import TradeChannel
from axile.server.api.routes.account_crud import _next_job_execution_times
from axile.server.cron import SCHEDULER_TIMEZONE, parse_cron_expr


def test_next_execution_times_skip_closed_weekend() -> None:
    trigger = parse_cron_expr("0 10 * * *")[0]
    job = SimpleNamespace(
        trigger=trigger,
        next_run_time=datetime(2026, 8, 28, 10, 0, tzinfo=SCHEDULER_TIMEZONE),
    )

    result = _next_job_execution_times(job, TradeChannel.CTP)

    assert result == [
        "2026-08-28T10:00:00+08:00",
        "2026-08-31T10:00:00+08:00",
        "2026-09-01T10:00:00+08:00",
    ]


def test_next_execution_times_keep_uncovered_dates_fail_open() -> None:
    trigger = parse_cron_expr("0 10 * * *")[0]
    job = SimpleNamespace(
        trigger=trigger,
        next_run_time=datetime(2027, 1, 1, 10, 0, tzinfo=SCHEDULER_TIMEZONE),
    )

    result = _next_job_execution_times(job, TradeChannel.CTP, limit=1)

    assert result == ["2027-01-01T10:00:00+08:00"]

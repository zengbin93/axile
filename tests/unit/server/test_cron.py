"""账户 crontab 组装与压缩 trigger 文本测试."""

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from axile.server.cron import (
    SCHEDULER_TIMEZONE,
    combine_cron_triggers,
    cron_triggers_equivalent,
    parse_cron_expr,
)


def test_compact_or_trigger_str_reports_count_not_fields() -> None:
    """APScheduler job 日志只应看到条数，不应展开 month/day 字段."""
    expr = " | ".join(f"{minute} 10,11,14,15 * * *" for minute in range(40))
    trigger = combine_cron_triggers(parse_cron_expr(expr))

    assert str(trigger) == "or[40 crontab]"
    assert "month=" not in str(trigger)
    assert "hour=" not in str(trigger)


def test_cron_triggers_equivalent_distinguishes_same_count_different_hours() -> None:
    """压缩 str 会碰撞时，对齐仍须按子 crontab 字段判断."""
    left = combine_cron_triggers(parse_cron_expr("0 10 * * * | 0 15 * * *"))
    right = combine_cron_triggers(parse_cron_expr("0 11 * * * | 0 16 * * *"))

    assert str(left) == str(right) == "or[2 crontab]"
    assert cron_triggers_equivalent(left, right) is False
    assert cron_triggers_equivalent(left, combine_cron_triggers(parse_cron_expr("0 10 * * * | 0 15 * * *"))) is True


def test_cron_triggers_equivalent_accepts_stock_or_trigger() -> None:
    """进程内旧的原版 OrTrigger 应能与压缩 trigger 对齐."""
    children = [
        CronTrigger.from_crontab("30 9 * * *", timezone=SCHEDULER_TIMEZONE),
        CronTrigger.from_crontab("0 15 * * *", timezone=SCHEDULER_TIMEZONE),
    ]
    stock = OrTrigger(children)
    compact = combine_cron_triggers(children)

    assert cron_triggers_equivalent(stock, compact) is True
    assert str(stock) != str(compact)

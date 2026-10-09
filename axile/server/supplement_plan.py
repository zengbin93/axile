"""预览与执行共用的独立补发计划；所有偏移相对基础计划时间。"""

from datetime import datetime, timedelta

from axile.channels import get_channel
from axile.channels.schedule_clock import parse_hhmm, window_contains
from axile.common.trade_channel import TradeChannel
from axile.server.cron import SCHEDULER_TIMEZONE, combine_cron_triggers, parse_cron_expr
from axile.server.db.models.account_settings import SupplementSettings
from axile.server.trading_calendar import CalendarDecisionStatus, evaluate_channel_calendar_moment


def session_end(channel: TradeChannel | str, base: datetime) -> datetime | None:
    """返回基础触发所在的交易窗右端点；连续交易返回空。"""
    local = base.astimezone(SCHEDULER_TIMEZONE)
    windows = get_channel(str(channel)).descriptor.schedule.windows
    for window in windows:
        start, end = parse_hhmm(window.start), parse_hhmm(window.end)
        if window_contains(start, end, local.time()):
            finish = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
            if finish <= local:
                finish += timedelta(days=1)
            return finish
    return local if windows else None


def plan_supplements(
    channel: TradeChannel | str, cron_expr: str, supplement: SupplementSettings, base: datetime
) -> tuple[list[datetime], datetime]:
    """裁掉跨交易窗及撞上下一基础触发的步骤，同时返回需求有效期。"""
    trigger = combine_cron_triggers(parse_cron_expr(cron_expr))
    next_base = trigger.get_next_fire_time(base, base)
    boundaries = [value for value in (next_base, session_end(channel, base)) if value is not None]
    expires = min(boundaries) if boundaries else base + timedelta(days=1)
    planned = [base]
    for index in range(1, supplement.count + 1):
        current = base + timedelta(minutes=index * supplement.interval_minutes)
        if current >= expires:
            break
        decision = evaluate_channel_calendar_moment(channel, current)
        if decision.status in {CalendarDecisionStatus.AVAILABLE_CLOSED, CalendarDecisionStatus.UNAVAILABLE}:
            break
        planned.append(current)
    return planned, expires

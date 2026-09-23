"""账户排程预览与统一活动流接口。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, cast

from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel, Field
from sqlmodel import col, desc, func, select

from axile.channels import get_channel
from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.utils.clock import clock_now
from axile.executor.trading_calendar import SHINNY_COVERAGE_END, SHINNY_COVERAGE_START
from axile.server.api.deps import SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.cron import SCHEDULER_TIMEZONE, is_blank_cron_expr, parse_cron_expr
from axile.server.db.models import (
    AccountActivityListPublic,
    ExecuteRecord,
    ExecutionActivity,
    ScheduleSkip,
    ScheduleSkipActivity,
)
from axile.server.db.models.performance import CostSummary
from axile.server.db.models.schedule import (
    ActivityExecutionRecord,
    ActivitySymbolListPublic,
    ActivitySymbolRowPublic,
    ScheduleSkipReason,
)
from axile.server.performance_costs import mapping, project_execution, summarize
from axile.server.trading_calendar import (
    CalendarDecisionStatus,
    CalendarSkipReason,
    CalendarUnavailableReason,
    evaluate_channel_calendar_moment,
)

router = APIRouter()


def _time_clauses(column, since: str | None, until: str | None):
    """把可选时间窗编成列比较；``since`` 含、``until`` 不含。"""
    clauses = []
    if since:
        clauses.append(column >= since)
    if until:
        clauses.append(column < until)
    return clauses


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _compact_execution_activity(row: ExecuteRecord) -> ExecutionActivity:
    """列表只发布状态、摘要数字和 total_asset。"""
    payload, trades = project_execution(row)
    raw = mapping(payload["record"].get("raw_result"))
    total = mapping(mapping(row.raw_result).get("account_assets")).get("total_asset")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total = None
    duration = payload.get("durationSec")
    return ExecutionActivity(
        occurred_at=row.created_at,
        record=ActivityExecutionRecord(
            id=row.id,
            execution_id=row.execution_id,
            created_at=row.created_at,
            is_success=row.is_success,
            status=_text_or_none(raw.get("status")),
            task_status=_text_or_none(raw.get("task_status")),
            error=_text_or_none(raw.get("error")),
            outcome=_text_or_none(raw.get("outcome")),
            outcome_reason=_text_or_none(raw.get("outcome_reason")),
            reason_code=_text_or_none(raw.get("reason_code")),
            execution_kind=_text_or_none(raw.get("execution_kind")),
            symbol_results=mapping(raw.get("symbol_results")),
            total_asset=float(total) if total is not None else None,
            summary=CostSummary.model_validate(summarize(trades)),
            duration_sec=duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
            trade_count=len(trades),
        ),
    )


def _projected_trades(row: ExecuteRecord) -> list[dict]:
    """把一次执行投影成带身份的成交行。"""
    _, trades = project_execution(row)
    return [{**trade, "record_id": row.id, "execution_id": row.execution_id} for trade in trades]


def _matches_trade(trade: dict, symbol: str | None, side: str | None) -> bool:
    if symbol and trade.get("symbol") != symbol:
        return False
    if side and trade.get("side") != side:
        return False
    return True


class SchedulePreviewRequest(BaseModel):
    """未来原始 Cron 触发点的只读预览请求。"""

    trade_channel: TradeChannel
    cron_expr: str
    after: AwareDatetime | None = None
    limit: int = Field(default=5, ge=1, le=100)


class SchedulePreviewCalendar(BaseModel):
    """排程预览对应渠道的轻量日历摘要。"""

    requirement: Literal["required", "not_required"]
    availability: Literal["available", "unavailable", "not_required"]
    unavailable_reason: CalendarUnavailableReason | None = None
    calendar_id: str | None = None
    label: str | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None


class SchedulePreviewItem(BaseModel):
    """单个未来 Cron 触发点及其轻量日历动作。"""

    scheduled_at: datetime
    calendar_day: date
    calendar_status: CalendarDecisionStatus
    action: Literal["execute", "skip"]
    unavailable_reason: CalendarUnavailableReason | None = None
    calendar_id: str | None = None
    label: str | None = None
    reason_code: CalendarSkipReason | None = None


class SchedulePreviewResponse(BaseModel):
    """账户排程预览响应。"""

    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    evaluated_at: datetime
    calendar: SchedulePreviewCalendar
    items: list[SchedulePreviewItem]
    next_cursor: datetime | None = None
    has_more: bool = False


def _field_error(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"type": "value_error", "loc": ["body", field], "msg": message, "input": None}],
    )


def _next_schedule_times(
    triggers: list[CronTrigger],
    *,
    start: datetime,
    limit: int,
    exclusive: bool = False,
) -> list[datetime]:
    """合并多个 CronTrigger，按北京时间返回去重后的未来触发点。"""
    next_values = [trigger.get_next_fire_time(None, start) for trigger in triggers]
    if exclusive:
        for index, value in enumerate(next_values):
            while value is not None and value <= start:
                value = triggers[index].get_next_fire_time(value, value)
            next_values[index] = value
    result: list[datetime] = []
    while len(result) < limit:
        candidates = [value for value in next_values if value is not None]
        if not candidates:
            break
        current = min(candidates)
        result.append(current)
        for index, value in enumerate(next_values):
            if value == current:
                next_values[index] = triggers[index].get_next_fire_time(current, current)
    return result


def _calendar_summary(channel: TradeChannel, current: datetime) -> SchedulePreviewCalendar:
    """返回渠道当前使用的 Shinny 日历摘要。"""
    declaration = get_channel(str(channel)).descriptor.calendar
    if declaration is None:
        return SchedulePreviewCalendar(requirement="not_required", availability="not_required")
    decision = evaluate_channel_calendar_moment(channel, current)
    return SchedulePreviewCalendar(
        requirement="required",
        availability=("unavailable" if decision.status is CalendarDecisionStatus.UNAVAILABLE else "available"),
        unavailable_reason=decision.unavailable_reason,
        calendar_id=declaration.calendar_id,
        label=declaration.label,
        coverage_start=SHINNY_COVERAGE_START,
        coverage_end=SHINNY_COVERAGE_END,
    )


@router.post("/schedule-preview", response_model=SchedulePreviewResponse)
async def schedule_preview(payload: SchedulePreviewRequest) -> SchedulePreviewResponse:
    """按时间游标只读预览未来 Cron 触发点及其交易日历动作。"""
    try:
        get_channel(str(payload.trade_channel))
    except KeyError as exc:
        raise _field_error("trade_channel", str(exc)) from exc

    evaluated_at = clock_now(tz=SCHEDULER_TIMEZONE)
    calendar = _calendar_summary(payload.trade_channel, evaluated_at)
    if is_blank_cron_expr(payload.cron_expr):
        return SchedulePreviewResponse(evaluated_at=evaluated_at, calendar=calendar, items=[])
    try:
        triggers = parse_cron_expr(payload.cron_expr)
    except ValueError as exc:
        raise _field_error("cron_expr", str(exc)) from exc

    start = payload.after.astimezone(SCHEDULER_TIMEZONE) if payload.after is not None else evaluated_at
    scheduled = _next_schedule_times(
        triggers,
        start=start,
        limit=payload.limit + 1,
        exclusive=payload.after is not None,
    )
    has_more = len(scheduled) > payload.limit
    page = scheduled[: payload.limit]
    items = []
    for scheduled_at in page:
        local_time = scheduled_at.astimezone(SCHEDULER_TIMEZONE)
        decision = evaluate_channel_calendar_moment(payload.trade_channel, local_time)
        items.append(
            SchedulePreviewItem(
                scheduled_at=local_time,
                calendar_day=decision.day,
                calendar_status=decision.status,
                action=(
                    "skip"
                    if decision.status in {CalendarDecisionStatus.AVAILABLE_CLOSED, CalendarDecisionStatus.UNAVAILABLE}
                    else "execute"
                ),
                unavailable_reason=decision.unavailable_reason,
                calendar_id=decision.calendar_id,
                label=decision.label,
                reason_code=decision.reason_code,
            )
        )
    return SchedulePreviewResponse(
        evaluated_at=evaluated_at,
        calendar=calendar,
        items=items,
        next_cursor=items[-1].scheduled_at if items else None,
        has_more=has_more,
    )


@router.get("/{account_id}/activity/symbols", response_model=ActivitySymbolListPublic)
async def account_activity_symbols(
    session: SessionDep,
    account_id: int,
    since: str,
    until: str,
    symbol: Annotated[str | None, Query()] = None,
) -> ActivitySymbolListPublic:
    """实时按品种汇总；时间窗必填。"""
    await _get_account_or_404(session, account_id)
    rows = (
        (
            await session.execute(
                select(ExecuteRecord)
                .where(
                    col(ExecuteRecord.account_id) == account_id,
                    *_time_clauses(col(ExecuteRecord.created_at), since, until),
                )
                .order_by(desc(col(ExecuteRecord.created_at)), desc(col(ExecuteRecord.id)))
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        for trade in _projected_trades(row):
            if not _matches_trade(trade, symbol, None):
                continue
            grouped.setdefault(str(trade["symbol"]), []).append(trade)
    data = [
        ActivitySymbolRowPublic(
            symbol=name,
            summary=CostSummary.model_validate(summarize(fills)),
            last_time=int(max(fill["time"] for fill in fills)),
            n_trades=len(fills),
            trades=fills if symbol else [],
        )
        for name, fills in grouped.items()
    ]
    return ActivitySymbolListPublic(data=data, count=len(data))


@router.get("/{account_id}/activity", response_model=AccountActivityListPublic)
async def account_activity(
    session: SessionDep,
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    since: Annotated[str | None, Query()] = None,
    until: Annotated[str | None, Query()] = None,
) -> AccountActivityListPublic:
    """合并执行与休市记录，按发生时间倒序分页。"""
    await _get_account_or_404(session, account_id)
    execution_where = [
        col(ExecuteRecord.account_id) == account_id,
        *_time_clauses(col(ExecuteRecord.created_at), since, until),
    ]
    skip_where = [
        col(ScheduleSkip.account_id) == account_id,
        *_time_clauses(col(ScheduleSkip.triggered_at), since, until),
    ]
    execution_count = await session.scalar(select(func.count()).select_from(ExecuteRecord).where(*execution_where))
    skip_count = await session.scalar(select(func.count()).select_from(ScheduleSkip).where(*skip_where))
    window = skip + limit
    execution_rows = (
        (
            await session.execute(
                select(ExecuteRecord)
                .where(*execution_where)
                .order_by(desc(col(ExecuteRecord.created_at)), desc(col(ExecuteRecord.id)))
                .limit(window)
            )
        )
        .scalars()
        .all()
    )
    skip_rows = (
        (
            await session.execute(
                select(ScheduleSkip)
                .where(*skip_where)
                .order_by(desc(col(ScheduleSkip.triggered_at)), desc(col(ScheduleSkip.id)))
                .limit(window)
            )
        )
        .scalars()
        .all()
    )

    activities: list[ExecutionActivity | ScheduleSkipActivity] = [
        _compact_execution_activity(row) for row in execution_rows
    ]
    activities.extend(
        ScheduleSkipActivity(
            occurred_at=row.triggered_at,
            id=cast(int, row.id),
            channel=row.channel,
            calendar_id=row.calendar_id,
            calendar_day=row.calendar_day,
            calendar_label=row.calendar_label,
            reason_code=cast("ScheduleSkipReason", row.reason_code),
        )
        for row in skip_rows
    )
    activities.sort(
        key=lambda item: (
            item.occurred_at,
            item.record.id if isinstance(item, ExecutionActivity) else item.id,
        ),
        reverse=True,
    )
    return AccountActivityListPublic(
        data=activities[skip:window],
        count=int(execution_count or 0) + int(skip_count or 0),
    )


__all__ = [
    "SchedulePreviewCalendar",
    "SchedulePreviewItem",
    "SchedulePreviewRequest",
    "SchedulePreviewResponse",
    "account_activity",
    "account_activity_symbols",
    "router",
]

"""账户排程预览与统一活动流接口。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel, Field
from sqlmodel import col, desc, func, select

from axile.channels import get_channel
from axile.common.trade_channel import TradeChannel
from axile.server.api.deps import SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.cron import SCHEDULER_TIMEZONE, is_blank_cron_expr, parse_cron_expr
from axile.server.db.models import (
    AccountActivityListPublic,
    ExecuteRecord,
    ExecuteRecordPublic,
    ExecutionActivity,
    ScheduleSkip,
    ScheduleSkipActivity,
)

router = APIRouter()


class SchedulePreviewRequest(BaseModel):
    """未来原始 Cron 触发点的只读预览请求。"""

    trade_channel: TradeChannel
    cron_expr: str
    after: AwareDatetime | None = None
    limit: int = Field(default=5, ge=1, le=100)


class SchedulePreviewItem(BaseModel):
    """单个未来 Cron 触发点。"""

    scheduled_at: datetime


class SchedulePreviewResponse(BaseModel):
    """账户排程预览响应。"""

    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    evaluated_at: datetime
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


@router.post("/schedule-preview", response_model=SchedulePreviewResponse)
async def schedule_preview(payload: SchedulePreviewRequest) -> SchedulePreviewResponse:
    """按时间游标只读预览未来 Cron 触发点及其交易日历动作。"""
    try:
        get_channel(str(payload.trade_channel))
    except KeyError as exc:
        raise _field_error("trade_channel", str(exc)) from exc

    evaluated_at = datetime.now(SCHEDULER_TIMEZONE)
    if is_blank_cron_expr(payload.cron_expr):
        return SchedulePreviewResponse(evaluated_at=evaluated_at, items=[])
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
    items = [SchedulePreviewItem(scheduled_at=value.astimezone(SCHEDULER_TIMEZONE)) for value in page]
    return SchedulePreviewResponse(
        evaluated_at=evaluated_at,
        items=items,
        next_cursor=items[-1].scheduled_at if items else None,
        has_more=has_more,
    )


@router.get("/{account_id}/activity", response_model=AccountActivityListPublic)
async def account_activity(
    session: SessionDep,
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> AccountActivityListPublic:
    """合并执行与休市记录，按发生时间倒序分页。"""
    await _get_account_or_404(session, account_id)
    execution_count = await session.scalar(
        select(func.count()).select_from(ExecuteRecord).where(col(ExecuteRecord.account_id) == account_id)
    )
    skip_count = await session.scalar(
        select(func.count()).select_from(ScheduleSkip).where(col(ScheduleSkip.account_id) == account_id)
    )
    window = skip + limit
    execution_rows = (
        (
            await session.execute(
                select(ExecuteRecord)
                .where(col(ExecuteRecord.account_id) == account_id)
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
                .where(col(ScheduleSkip.account_id) == account_id)
                .order_by(desc(col(ScheduleSkip.triggered_at)), desc(col(ScheduleSkip.id)))
                .limit(window)
            )
        )
        .scalars()
        .all()
    )
    activities: list[ExecutionActivity | ScheduleSkipActivity] = [
        ExecutionActivity(
            occurred_at=row.created_at,
            record=ExecuteRecordPublic.model_validate(row),
        )
        for row in execution_rows
    ]
    activities.extend(
        ScheduleSkipActivity(
            occurred_at=row.triggered_at,
            id=cast(int, row.id),
            channel=row.channel,
            calendar_id=row.calendar_id,
            calendar_day=row.calendar_day,
            calendar_label=row.calendar_label,
            reason_code="CALENDAR.CLOSED",
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
    "SchedulePreviewItem",
    "SchedulePreviewRequest",
    "SchedulePreviewResponse",
    "router",
]

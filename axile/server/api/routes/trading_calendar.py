"""插件交易日历查询与维护路由。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from axile.server.api.deps import SessionDep
from axile.server.trading_calendar import (
    CALENDAR_ID,
    CALENDAR_INITIAL_HISTORY_DAYS,
    CALENDAR_TARGET_FUTURE_DAYS,
    CalendarDiagnosticEntry,
    CalendarFunctionResult,
    CalendarImportPreview,
    CalendarOverrideEntry,
    CalendarOverrideInput,
    CalendarStatus,
    TradingCalendarEntry,
    build_import_preview,
    clear_calendar_overrides,
    get_calendar_status,
    import_calendar_csv,
    list_calendar_diagnostics,
    list_calendar_entries,
    list_calendar_overrides,
    parse_calendar_csv,
    run_calendar_function,
    save_calendar_function,
    save_shinny_calendar,
    save_tushare_calendar,
    set_calendar_overrides,
    sync_calendar_python,
    sync_calendar_shinny,
    sync_calendar_tushare,
)

router = APIRouter(prefix="/market/trading-calendar", tags=["market"])


class FunctionRequest(BaseModel):
    """Python 日历函数载荷。"""

    model_config = {"populate_by_name": True}
    calendar_id: str = Field(default=CALENDAR_ID, alias="calendarId")
    function_code: str = Field(alias="functionCode")
    start: date | None = None
    end: date | None = None


class OverridesRequest(BaseModel):
    """批量人工调整载荷。"""

    entries: list[CalendarOverrideInput]


class RestoreOverridesRequest(BaseModel):
    """恢复基础值载荷。"""

    model_config = {"populate_by_name": True}
    dates: list[date]
    calendar_id: str = Field(default=CALENDAR_ID, alias="calendarId")


class OperationResult(BaseModel):
    """维护操作结果。"""

    ok: bool
    message: str


@router.get("", response_model=list[TradingCalendarEntry], response_model_by_alias=True)
async def get_trading_calendar(
    session: SessionDep,
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
    start: date | None = None,
    end: date | None = None,
    only_open: Annotated[bool, Query(alias="onlyOpen")] = False,
) -> list[TradingCalendarEntry]:
    """返回最终有效的日历状态。"""
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start 必须 <= end")
    try:
        return await list_calendar_entries(session, calendar_id=calendar_id, start=start, end=end, only_open=only_open)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/status", response_model=CalendarStatus, response_model_by_alias=True)
async def calendar_status(
    session: SessionDep,
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> CalendarStatus:
    """返回维护工作台摘要。"""
    return await get_calendar_status(session, calendar_id)


@router.get("/diagnostics", response_model=list[CalendarDiagnosticEntry], response_model_by_alias=True)
async def calendar_diagnostics(
    session: SessionDep,
    start: date,
    end: date,
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> list[CalendarDiagnosticEntry]:
    """返回连续区间内的基础值、覆盖与最终状态。"""
    if start > end:
        raise HTTPException(status_code=422, detail="start 必须 <= end")
    if (end - start).days > 92:
        raise HTTPException(status_code=422, detail="单次最多加载 93 个自然日")
    return await list_calendar_diagnostics(session, calendar_id=calendar_id, start=start, end=end)


@router.post("/csv/preview", response_model=CalendarImportPreview, response_model_by_alias=True)
async def preview_calendar_csv(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> CalendarImportPreview:
    """解析 CSV 并返回即时差异，不保存文件或预览状态。"""
    try:
        return await build_import_preview(session, parse_calendar_csv(await file.read(), calendar_id=calendar_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/csv/import", response_model=CalendarImportPreview, response_model_by_alias=True)
async def import_calendar_file(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> CalendarImportPreview:
    """重新校验上传文件并原子替换基础日历。"""
    try:
        return await import_calendar_csv(session, await file.read(), calendar_id=calendar_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/python/validate", response_model=CalendarFunctionResult, response_model_by_alias=True)
async def validate_calendar_function(payload: FunctionRequest) -> CalendarFunctionResult:
    """在隔离子进程中试跑 Python 日历函数。"""
    start = payload.start or date.today()
    end = payload.end or start + timedelta(days=6)
    if start > end:
        raise HTTPException(status_code=422, detail="start 必须 <= end")
    if (end - start).days > 92:
        raise HTTPException(status_code=422, detail="试跑区间最多 93 天")
    return await run_calendar_function(payload.function_code, start, end, calendar_id=payload.calendar_id)


@router.put("/python", response_model=CalendarStatus, response_model_by_alias=True)
async def update_calendar_function(session: SessionDep, payload: FunctionRequest) -> CalendarStatus:
    """执行 Python 函数并在成功后保存代码与基础日历。"""
    try:
        await save_calendar_function(session, calendar_id=payload.calendar_id, function_code=payload.function_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await get_calendar_status(session, payload.calendar_id)


@router.put("/shinny", response_model=CalendarStatus, response_model_by_alias=True)
async def update_shinny_calendar(
    session: SessionDep,
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> CalendarStatus:
    """物化 Shinny 中国期货/通用节假日日历；内置数据仅覆盖至 2026 年。"""
    today = date.today()
    try:
        await save_shinny_calendar(
            session,
            calendar_id=calendar_id,
            start=today - timedelta(days=CALENDAR_INITIAL_HISTORY_DAYS),
            end=today + timedelta(days=CALENDAR_TARGET_FUTURE_DAYS),
        )
    except ValueError as exc:
        logger.warning("刷新 {} Shinny 交易日历失败: {}", calendar_id, type(exc).__name__)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await get_calendar_status(session, calendar_id)


@router.put("/tushare", response_model=CalendarStatus, response_model_by_alias=True)
async def update_tushare_calendar(
    session: SessionDep,
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> CalendarStatus:
    """用 config.toml 中的 Tushare 凭据生成并保存日历。"""
    today = date.today()
    try:
        await save_tushare_calendar(
            session,
            calendar_id=calendar_id,
            start=today - timedelta(days=CALENDAR_INITIAL_HISTORY_DAYS),
            end=today + timedelta(days=CALENDAR_TARGET_FUTURE_DAYS),
        )
    except ValueError as exc:
        logger.warning("刷新 {} Tushare 交易日历失败: {}", calendar_id, type(exc).__name__)
        raise HTTPException(status_code=422, detail="Tushare 交易日历配置或数据无效") from exc
    except Exception as exc:  # noqa: BLE001 - 不回显上游响应或凭据
        logger.warning("刷新 {} Tushare 交易日历失败: {}", calendar_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="Tushare 交易日历拉取失败") from exc
    return await get_calendar_status(session, calendar_id)


@router.post("/refresh", response_model=OperationResult)
async def refresh_calendar(
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> OperationResult:
    """立即执行一次已配置的 Python、Shinny 或 Tushare 刷新。"""
    refreshed = await sync_calendar_python(calendar_id=calendar_id, force=True)
    if not refreshed:
        refreshed = await sync_calendar_shinny(calendar_id=calendar_id, force=True)
    if not refreshed:
        refreshed = await sync_calendar_tushare(calendar_id=calendar_id, force=True)
    return OperationResult(
        ok=refreshed,
        message="刷新完成" if refreshed else "未刷新：未配置自动刷新、已有刷新运行或数据拉取失败",
    )


@router.put("/overrides", response_model=OperationResult)
async def update_calendar_overrides(session: SessionDep, payload: OverridesRequest) -> OperationResult:
    """保存逐日人工修正。"""
    await set_calendar_overrides(session, payload.entries)
    return OperationResult(ok=True, message=f"已保存 {len(payload.entries)} 条人工调整")


@router.get("/overrides", response_model=list[CalendarOverrideEntry], response_model_by_alias=True)
async def calendar_overrides(
    session: SessionDep,
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> list[CalendarOverrideEntry]:
    """返回当前全部人工调整。"""
    return await list_calendar_overrides(session, calendar_id=calendar_id)


@router.post("/overrides/restore", response_model=OperationResult)
async def restore_calendar_overrides(session: SessionDep, payload: RestoreOverridesRequest) -> OperationResult:
    """清除人工调整并恢复基础值。"""
    await clear_calendar_overrides(session, payload.dates, calendar_id=payload.calendar_id)
    return OperationResult(ok=True, message=f"已恢复 {len(payload.dates)} 个日期")


@router.get("/template")
async def calendar_csv_template(
    calendar_id: Annotated[str, Query(alias="calendarId", min_length=1)] = CALENDAR_ID,
) -> dict[str, str]:
    """返回可直接下载的 CSV 模板内容。"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return {
        "filename": f"trading-calendar-{calendar_id}.csv",
        "content": (
            f"calendar_id,cal_date,is_open\n{calendar_id},{today.isoformat()},true\n"
            f"{calendar_id},{tomorrow.isoformat()},true\n"
        ),
    }


__all__ = ["router"]

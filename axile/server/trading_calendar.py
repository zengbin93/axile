"""插件交易日历的替换、查询、覆盖与同步。"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, ValidationError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, func, select

from axile.channels import get_channel
from axile.common.config import CONFIG_TOML_PATH
from axile.common.trade_channel import TradeChannel
from axile.executor.china_futures_session import is_regular_night_session_transition
from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import TradingCalendarConfig, TradingCalendarOverride, TradingCalendarRecord
from axile.server.db.models.base import now_str
from axile.server.sandbox import ScriptExecutionError, run_calendar_script

try:
    from shinny_calendar import CalendarUtility
except ImportError:
    CalendarUtility = None  # type: ignore[assignment,misc]

CALENDAR_ID = "china"
CALENDAR_MIN_FUTURE_DAYS = 14
CALENDAR_TARGET_FUTURE_DAYS = 365
CALENDAR_INITIAL_HISTORY_DAYS = 365
CALENDAR_JOB_ID = "ensure-trading-calendar"
SHINNY_CALENDAR_REFRESH_KIND = "shinny"
TUSHARE_CALENDAR_REFRESH_KIND = "tushare"
SHINNY_CALENDAR_LAST_YEAR = 2026

type CalendarRefreshKind = Literal["csv", "python", "shinny", "tushare"]
type CalendarSkipReason = Literal["CALENDAR.CLOSED", "CALENDAR.NO_NIGHT_SESSION"]
_CALENDAR_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_SYNC_LOCKS: dict[str, asyncio.Lock] = {}
PENDING_CALENDAR_PATH = CONFIG_TOML_PATH.with_name(f"{CONFIG_TOML_PATH.stem}.trading-calendar.json")


def normalize_calendar_id(calendar_id: str) -> str:
    """规范化并校验插件声明的日历标识。"""
    value = calendar_id.strip().lower()
    if not _CALENDAR_ID_PATTERN.fullmatch(value):
        raise ValueError("calendar_id 必须是小写字母开头的稳定标识，可包含数字、下划线和连字符")
    return value


class CalendarInputEntry(BaseModel):
    """一次刷新返回的一天日历状态。"""

    model_config = ConfigDict(extra="forbid")
    calendar_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    cal_date: date
    is_open: StrictBool


class TradingCalendarEntry(BaseModel):
    """执行器消费的最终交易日历行。"""

    model_config = ConfigDict(populate_by_name=True)
    calendar_id: str = Field(alias="calendarId")
    cal_date: date = Field(alias="calDate")
    is_open: bool = Field(alias="isOpen")
    pretrade_date: date | None = Field(default=None, alias="pretradeDate")


class CalendarDiagnosticEntry(BaseModel):
    """单日基础值、人工覆盖与最终值。"""

    model_config = ConfigDict(populate_by_name=True)
    calendar_id: str = Field(alias="calendarId")
    cal_date: date = Field(alias="calDate")
    base_is_open: bool | None = Field(default=None, alias="baseIsOpen")
    override_is_open: bool | None = Field(default=None, alias="overrideIsOpen")
    is_open: bool | None = Field(default=None, alias="isOpen")


class CalendarDecisionStatus(str, Enum):
    """渠道在指定日期的交易日历判断结果。"""

    NOT_REQUIRED = "not_required"
    AVAILABLE_OPEN = "available_open"
    AVAILABLE_CLOSED = "available_closed"
    UNAVAILABLE = "unavailable"


class CalendarUnavailableReason(str, Enum):
    """交易日历无法给出结论的原因。"""

    NOT_CONFIGURED = "not_configured"
    UNCOVERED = "uncovered"
    READ_FAILED = "read_failed"


class CalendarDayDecision(BaseModel):
    """渠道在单个自然日上的日历决策。"""

    channel: str
    day: date
    calendar_id: str | None = None
    label: str | None = None
    status: CalendarDecisionStatus
    unavailable_reason: CalendarUnavailableReason | None = None
    base_is_open: bool | None = None
    override_is_open: bool | None = None
    effective_is_open: bool | None = None
    reason_code: CalendarSkipReason | None = None


class CalendarAvailability(str, Enum):
    """日历对当前日期的派生可用性。"""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class CalendarImportPreview(BaseModel):
    """替换基础数据前的差异摘要。"""

    start: date
    end: date
    total: int
    added: int
    changed: int
    unchanged: int


class CalendarFunctionResult(BaseModel):
    """自定义 Python 函数试跑结果。"""

    model_config = ConfigDict(populate_by_name=True)
    valid: bool
    entries: list[CalendarInputEntry] = Field(default_factory=list)
    error: str | None = None
    traceback: str | None = None
    error_line: int | None = Field(default=None, alias="errorLine")
    error_offset: int | None = Field(default=None, alias="errorOffset")
    error_type: str | None = Field(default=None, alias="errorType")
    error_message: str | None = Field(default=None, alias="errorMessage")


class CalendarStatus(BaseModel):
    """一份插件日历的运行状态。"""

    model_config = ConfigDict(populate_by_name=True)
    calendar_id: str = Field(alias="calendarId")
    availability: CalendarAvailability
    unavailable_reason: CalendarUnavailableReason | None = Field(default=None, alias="unavailableReason")
    refresh_kind: CalendarRefreshKind | None = Field(default=None, alias="refreshKind")
    function_code: str = Field(default="", alias="functionCode")
    coverage_start: date | None = Field(default=None, alias="coverageStart")
    coverage_end: date | None = Field(default=None, alias="coverageEnd")
    override_count: int = Field(default=0, alias="overrideCount")
    last_sync_at: str | None = Field(default=None, alias="lastSyncAt")


class CalendarOverrideInput(BaseModel):
    """人工调整输入。"""

    model_config = ConfigDict(populate_by_name=True)
    calendar_id: str = Field(default=CALENDAR_ID, alias="calendarId")
    cal_date: date = Field(alias="calDate")
    is_open: StrictBool = Field(alias="isOpen")


class CalendarOverrideEntry(CalendarOverrideInput):
    """人工调整及当前基础值。"""

    base_is_open: bool | None = Field(default=None, alias="baseIsOpen")
    updated_at: str = Field(alias="updatedAt")


_ENTRY_LIST_ADAPTER = TypeAdapter(list[CalendarInputEntry])


async def list_calendar_diagnostics(
    session: AsyncSession,
    *,
    calendar_id: str = CALENDAR_ID,
    start: date,
    end: date,
) -> list[CalendarDiagnosticEntry]:
    """读取连续区间内的基础值、覆盖和最终状态。"""
    calendar_id = normalize_calendar_id(calendar_id)
    if start > end:
        raise ValueError("start 必须 <= end")
    base_rows = (
        await session.execute(
            select(TradingCalendarRecord).where(
                col(TradingCalendarRecord.calendar_id) == calendar_id,
                col(TradingCalendarRecord.cal_date) >= start,
                col(TradingCalendarRecord.cal_date) <= end,
            )
        )
    ).scalars()
    override_rows = (
        await session.execute(
            select(TradingCalendarOverride).where(
                col(TradingCalendarOverride.calendar_id) == calendar_id,
                col(TradingCalendarOverride.cal_date) >= start,
                col(TradingCalendarOverride.cal_date) <= end,
            )
        )
    ).scalars()
    base = {row.cal_date: row.is_open for row in base_rows}
    overrides = {row.cal_date: row.is_open for row in override_rows}
    rows: list[CalendarDiagnosticEntry] = []
    current = start
    while current <= end:
        base_value = base.get(current)
        override_value = overrides.get(current)
        rows.append(
            CalendarDiagnosticEntry(
                calendarId=calendar_id,
                calDate=current,
                baseIsOpen=base_value,
                overrideIsOpen=override_value,
                isOpen=override_value if override_value is not None else base_value,
            )
        )
        current += timedelta(days=1)
    return rows


def _decision_from_diagnostic(
    *, channel: str, label: str, row: CalendarDiagnosticEntry, configured: bool
) -> CalendarDayDecision:
    """把单日诊断转换为渠道决策。"""
    effective = row.is_open
    if effective is None:
        return CalendarDayDecision(
            channel=channel,
            day=row.cal_date,
            calendar_id=row.calendar_id,
            label=label,
            status=CalendarDecisionStatus.UNAVAILABLE,
            unavailable_reason=(
                CalendarUnavailableReason.UNCOVERED if configured else CalendarUnavailableReason.NOT_CONFIGURED
            ),
        )
    return CalendarDayDecision(
        channel=channel,
        day=row.cal_date,
        calendar_id=row.calendar_id,
        label=label,
        status=CalendarDecisionStatus.AVAILABLE_OPEN if effective else CalendarDecisionStatus.AVAILABLE_CLOSED,
        base_is_open=row.base_is_open,
        override_is_open=row.override_is_open,
        effective_is_open=effective,
    )


async def evaluate_channel_calendar_days(
    session: AsyncSession, channel: TradeChannel | str, days: Sequence[date]
) -> dict[date, CalendarDayDecision]:
    """批量判断一个渠道在指定自然日上的日历可用性。"""
    unique_days = sorted(set(days))
    if not unique_days:
        return {}
    channel_name = str(channel)
    calendar = get_channel(channel_name).descriptor.calendar
    if calendar is None:
        return {
            day: CalendarDayDecision(channel=channel_name, day=day, status=CalendarDecisionStatus.NOT_REQUIRED)
            for day in unique_days
        }
    try:
        configured = await session.get(TradingCalendarConfig, calendar.calendar_id) is not None
        diagnostics = await list_calendar_diagnostics(
            session, calendar_id=calendar.calendar_id, start=unique_days[0], end=unique_days[-1]
        )
    except Exception as exc:  # noqa: BLE001 - 读取失败按产品约定放行
        logger.warning("读取 {} 交易日历失败，按排程执行: {}", calendar.calendar_id, exc)
        return {
            day: CalendarDayDecision(
                channel=channel_name,
                day=day,
                calendar_id=calendar.calendar_id,
                label=calendar.label,
                status=CalendarDecisionStatus.UNAVAILABLE,
                unavailable_reason=CalendarUnavailableReason.READ_FAILED,
            )
            for day in unique_days
        }
    by_day = {row.cal_date: row for row in diagnostics}
    return {
        day: _decision_from_diagnostic(
            channel=channel_name, label=calendar.label, row=by_day[day], configured=configured
        )
        for day in unique_days
    }


async def evaluate_channel_calendar_day(
    session: AsyncSession, channel: TradeChannel | str, day: date
) -> CalendarDayDecision:
    """判断一个渠道在单个自然日上的日历可用性。"""
    return (await evaluate_channel_calendar_days(session, channel, [day]))[day]


def _china_futures_night_start(current: datetime) -> date | None:
    """返回期货夜盘所属的起始自然日，日盘时段返回 ``None``。"""
    local_time = current.timetz().replace(tzinfo=None)
    if local_time >= time(21):
        return current.date()
    if local_time <= time(2, 30):
        return current.date() - timedelta(days=1)
    return None


async def evaluate_channel_calendar_moment(
    session: AsyncSession,
    channel: TradeChannel | str,
    current: datetime,
) -> CalendarDayDecision:
    """按渠道时段把一次触发映射到交易日并判断是否执行。"""
    channel_name = str(channel)
    descriptor = get_channel(channel_name).descriptor
    session_start = (
        _china_futures_night_start(current)
        if descriptor.schedule.kind == "cn_futures" and descriptor.schedule.night is not None
        else None
    )
    if session_start is None:
        decision = await evaluate_channel_calendar_day(session, channel, current.date())
        if decision.status is CalendarDecisionStatus.AVAILABLE_CLOSED:
            return decision.model_copy(update={"reason_code": "CALENDAR.CLOSED"})
        return decision

    nominal_day = session_start + timedelta(days=1)
    days = [session_start + timedelta(days=offset) for offset in range(15)]
    decisions = await evaluate_channel_calendar_days(session, channel, days)
    start_decision = decisions[session_start]
    if start_decision.status is CalendarDecisionStatus.NOT_REQUIRED:
        return start_decision.model_copy(update={"day": nominal_day})
    if start_decision.status is CalendarDecisionStatus.UNAVAILABLE:
        return start_decision.model_copy(update={"day": nominal_day})
    if start_decision.status is CalendarDecisionStatus.AVAILABLE_CLOSED:
        return start_decision.model_copy(update={"reason_code": "CALENDAR.NO_NIGHT_SESSION"})

    for day in days[1:]:
        candidate = decisions[day]
        if candidate.status is CalendarDecisionStatus.UNAVAILABLE:
            return candidate
        if candidate.status is not CalendarDecisionStatus.AVAILABLE_OPEN:
            continue
        if is_regular_night_session_transition(session_start, day):
            return candidate
        return candidate.model_copy(
            update={
                "status": CalendarDecisionStatus.AVAILABLE_CLOSED,
                "effective_is_open": False,
                "reason_code": "CALENDAR.NO_NIGHT_SESSION",
            }
        )

    return start_decision.model_copy(
        update={
            "day": nominal_day,
            "status": CalendarDecisionStatus.AVAILABLE_CLOSED,
            "effective_is_open": False,
            "reason_code": "CALENDAR.NO_NIGHT_SESSION",
        }
    )


async def list_calendar_entries(
    session: AsyncSession,
    *,
    calendar_id: str = CALENDAR_ID,
    start: date | None = None,
    end: date | None = None,
    only_open: bool = False,
) -> list[TradingCalendarEntry]:
    """返回一份插件日历的最终有效状态。"""
    calendar_id = normalize_calendar_id(calendar_id)
    if start is None or end is None:
        bounds: list[tuple[date | None, date | None]] = []
        for model in (TradingCalendarRecord, TradingCalendarOverride):
            row = (
                await session.execute(
                    select(func.min(col(model.cal_date)), func.max(col(model.cal_date))).where(
                        col(model.calendar_id) == calendar_id
                    )
                )
            ).one()
            bounds.append(cast("tuple[date | None, date | None]", row))
        minima = [cast(date, lower) for lower, _ in bounds if lower is not None]
        maxima = [cast(date, upper) for _, upper in bounds if upper is not None]
        if not minima or not maxima:
            return []
        start = start or min(minima)
        end = end or max(maxima)
    diagnostics = await list_calendar_diagnostics(
        session, calendar_id=calendar_id, start=start - timedelta(days=366), end=end
    )
    visible = [
        row
        for row in diagnostics
        if row.cal_date >= start and row.is_open is not None and (not only_open or row.is_open)
    ]
    open_dates = [row.cal_date for row in diagnostics if row.is_open is True]
    return [
        TradingCalendarEntry(
            calendarId=calendar_id,
            calDate=row.cal_date,
            isOpen=cast(bool, row.is_open),
            pretradeDate=max((day for day in open_dates if day < row.cal_date), default=None),
        )
        for row in visible
    ]


def parse_calendar_csv(content: bytes, *, calendar_id: str = CALENDAR_ID) -> list[CalendarInputEntry]:
    """解析并严格校验 UTF-8 CSV 日历。"""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 必须使用 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(text))
    expected = ["calendar_id", "cal_date", "is_open"]
    if reader.fieldnames != expected:
        raise ValueError(f"CSV 表头必须严格为 {','.join(expected)}")
    raw: list[dict[str, Any]] = []
    for line_number, row in enumerate(reader, start=2):
        value = (row.get("is_open") or "").strip().lower()
        if value not in {"true", "false"}:
            raise ValueError(f"第 {line_number} 行 is_open 必须为 true 或 false")
        raw.append(
            {
                "calendar_id": (row.get("calendar_id") or "").strip().lower(),
                "cal_date": (row.get("cal_date") or "").strip(),
                "is_open": value == "true",
            }
        )
    try:
        entries = _ENTRY_LIST_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    validate_calendar_entries(entries, calendar_id=calendar_id)
    return entries


def validate_calendar_entries(
    entries: list[CalendarInputEntry],
    *,
    calendar_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> None:
    """校验记录属于同一日历且完整覆盖连续自然日区间。"""
    if not entries:
        raise ValueError("交易日历不能为空")
    expected_id = normalize_calendar_id(calendar_id or entries[0].calendar_id)
    if any(entry.calendar_id != expected_id for entry in entries):
        raise ValueError(f"所有记录的 calendar_id 必须为 {expected_id}")
    dates = [entry.cal_date for entry in entries]
    if len(set(dates)) != len(dates):
        raise ValueError("交易日历包含重复日期")
    lower = start or min(dates)
    upper = end or max(dates)
    if min(dates) != lower or max(dates) != upper:
        raise ValueError(f"交易日历必须覆盖 {lower.isoformat()} 至 {upper.isoformat()}")
    expected = (upper - lower).days + 1
    if len(entries) != expected:
        raise ValueError(f"交易日历区间缺少 {expected - len(entries)} 个自然日")


def _validate_calendar_function_entries(
    entries: list[CalendarInputEntry], *, calendar_id: str, start: date, end: date
) -> None:
    """校验自定义函数返回请求范围内的一段连续交易日历。"""
    validate_calendar_entries(entries, calendar_id=calendar_id)
    dates = [entry.cal_date for entry in entries]
    if min(dates) < start or max(dates) > end:
        raise ValueError(f"交易日历日期必须位于 {start.isoformat()} 至 {end.isoformat()} 内")


async def build_import_preview(session: AsyncSession, entries: list[CalendarInputEntry]) -> CalendarImportPreview:
    """比较候选基础日历与当前数据。"""
    validate_calendar_entries(entries)
    calendar_id = entries[0].calendar_id
    rows = (
        await session.execute(
            select(TradingCalendarRecord).where(col(TradingCalendarRecord.calendar_id) == calendar_id)
        )
    ).scalars()
    existing = {row.cal_date: row.is_open for row in rows}
    return CalendarImportPreview(
        start=min(entry.cal_date for entry in entries),
        end=max(entry.cal_date for entry in entries),
        total=len(entries),
        added=sum(entry.cal_date not in existing for entry in entries),
        changed=sum(entry.cal_date in existing and existing[entry.cal_date] != entry.is_open for entry in entries),
        unchanged=sum(entry.cal_date in existing and existing[entry.cal_date] == entry.is_open for entry in entries),
    )


async def _replace_calendar(
    session: AsyncSession,
    entries: list[CalendarInputEntry],
    *,
    refresh_kind: CalendarRefreshKind,
    function_code: str = "",
) -> None:
    """在一个事务内替换基础数据、刷新配置并清空人工覆盖。"""
    validate_calendar_entries(entries)
    calendar_id = entries[0].calendar_id
    try:
        await session.execute(
            delete(TradingCalendarRecord).where(col(TradingCalendarRecord.calendar_id) == calendar_id)
        )
        await session.execute(
            delete(TradingCalendarOverride).where(col(TradingCalendarOverride.calendar_id) == calendar_id)
        )
        session.add_all(
            [
                TradingCalendarRecord(
                    calendar_id=calendar_id,
                    cal_date=entry.cal_date,
                    is_open=entry.is_open,
                    updated_at=now_str(),
                )
                for entry in entries
            ]
        )
        config = await session.get(TradingCalendarConfig, calendar_id)
        if config is None:
            config = TradingCalendarConfig(calendar_id=calendar_id, refresh_kind=refresh_kind)
            session.add(config)
        config.refresh_kind = refresh_kind
        config.function_code = function_code if refresh_kind == "python" else ""
        config.last_sync_at = now_str()
        config.updated_at = now_str()
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def stage_initial_calendars(calendars: list[dict[str, Any]]) -> None:
    """原子暂存向导最终选定的单源日历，供重启后写入数据库。"""
    if not calendars:
        PENDING_CALENDAR_PATH.unlink(missing_ok=True)
        return
    payload = {"calendars": calendars}
    temporary = Path(f"{PENDING_CALENDAR_PATH}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(PENDING_CALENDAR_PATH)


async def apply_pending_initial_calendars() -> None:
    """数据库就绪后应用向导日历；失败时保留暂存文件供下次启动重试。"""
    if not PENDING_CALENDAR_PATH.exists():
        return
    try:
        payload = json.loads(PENDING_CALENDAR_PATH.read_text(encoding="utf-8"))
        async with SessionLocal() as session:
            for item in payload.get("calendars", []):
                calendar_id = normalize_calendar_id(str(item["calendar_id"]))
                entries = _ENTRY_LIST_ADAPTER.validate_python(item["entries"])
                refresh_kind = cast(CalendarRefreshKind, item["refresh_kind"])
                if refresh_kind not in {"csv", "python"}:
                    raise ValueError(f"不支持的日历刷新方式: {refresh_kind}")
                validate_calendar_entries(entries, calendar_id=calendar_id)
                await _replace_calendar(
                    session,
                    entries,
                    refresh_kind=refresh_kind,
                    function_code=str(item.get("function_code", "")),
                )
    except Exception as exc:  # noqa: BLE001 - 启动失败时仍按 fail-open 运行并保留重试材料
        logger.warning("应用初始化交易日历失败，继续按原排程执行: {}", exc)
        return
    PENDING_CALENDAR_PATH.unlink(missing_ok=True)


async def import_calendar_csv(
    session: AsyncSession, content: bytes, *, calendar_id: str = CALENDAR_ID
) -> CalendarImportPreview:
    """校验并原子替换基础日历。"""
    calendar_id = normalize_calendar_id(calendar_id)
    entries = parse_calendar_csv(content, calendar_id=calendar_id)
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    async with lock:
        preview = await build_import_preview(session, entries)
        await _replace_calendar(session, entries, refresh_kind="csv")
    return preview


def _build_shinny_calendar_entries(calendar_id: str, start: date, end: date) -> list[CalendarInputEntry]:
    """将 shinny 的中国期货/节假日判断物化为可供执行器读取的自然日日历。"""
    if calendar_id != CALENDAR_ID:
        raise ValueError("Shinny 兜底仅支持 china 日历")
    if CalendarUtility is None:
        raise ValueError("未安装 shinny-calendar，请安装 axile[shinny]")
    last_supported_day = min(end, date(SHINNY_CALENDAR_LAST_YEAR, 12, 31))
    if start > last_supported_day:
        raise ValueError(f"Shinny 内置节假日仅覆盖至 {SHINNY_CALENDAR_LAST_YEAR}-12-31")
    calendar = CalendarUtility()
    return [
        CalendarInputEntry(
            calendar_id=calendar_id,
            cal_date=day,
            is_open=calendar.trading_day(datetime.combine(day, time.min)) == day,
        )
        for day in (start + timedelta(days=offset) for offset in range((last_supported_day - start).days + 1))
    ]


async def _save_shinny_calendar(session: AsyncSession, *, calendar_id: str, start: date, end: date) -> None:
    """在已持有日历锁时物化 Shinny 本地兜底日历。"""
    entries = await asyncio.to_thread(_build_shinny_calendar_entries, calendar_id, start, end)
    await _replace_calendar(session, entries, refresh_kind=SHINNY_CALENDAR_REFRESH_KIND)


async def save_shinny_calendar(
    session: AsyncSession,
    *,
    calendar_id: str = CALENDAR_ID,
    start: date,
    end: date,
) -> None:
    """用 Shinny 物化中国期货/通用节假日日历，2026 年后不再生成数据。"""
    calendar_id = normalize_calendar_id(calendar_id)
    if start > end:
        raise ValueError("start 必须 <= end")
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    async with lock:
        await _save_shinny_calendar(session, calendar_id=calendar_id, start=start, end=end)


async def fetch_tushare_trade_cal(start: date, end: date) -> list[dict[str, str]]:
    """从 config.toml 读取凭据并拉取 Tushare 全量交易日历。"""
    from axile.common.config import settings

    token = settings.tushare_token.strip()
    if not token:
        raise ValueError("未配置 Tushare Token")

    def fetch() -> list[dict[str, str]]:
        import tushare as ts

        client = ts.pro_api(token)
        frame = client.trade_cal(exchange="SSE", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
        return cast("list[dict[str, str]]", frame.to_dict("records"))

    return await asyncio.to_thread(fetch)


async def _save_tushare_calendar(session: AsyncSession, *, calendar_id: str, start: date, end: date) -> None:
    """在已持有日历锁时拉取并替换 Tushare 日历。"""
    rows = await fetch_tushare_trade_cal(start, end)
    entries = [
        CalendarInputEntry(
            calendar_id=calendar_id,
            cal_date=datetime.strptime(str(row["cal_date"]), "%Y%m%d").date(),
            is_open=str(row["is_open"]) == "1",
        )
        for row in rows
    ]
    validate_calendar_entries(entries, calendar_id=calendar_id, start=start, end=end)
    await _replace_calendar(session, entries, refresh_kind=TUSHARE_CALENDAR_REFRESH_KIND)


async def save_tushare_calendar(
    session: AsyncSession,
    *,
    calendar_id: str = CALENDAR_ID,
    start: date,
    end: date,
) -> None:
    """用 Tushare trade_cal 原子替换一份日历；凭据不入库。"""
    calendar_id = normalize_calendar_id(calendar_id)
    if start > end:
        raise ValueError("start 必须 <= end")
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    async with lock:
        await _save_tushare_calendar(session, calendar_id=calendar_id, start=start, end=end)


def _calendar_script_error(error: ScriptExecutionError) -> CalendarFunctionResult:
    return CalendarFunctionResult(
        valid=False,
        error=str(error),
        traceback=error.formatted_traceback,
        errorLine=error.error_line,
        errorOffset=error.error_offset,
        errorType=error.error_type,
        errorMessage=error.error_message,
    )


async def run_calendar_function(
    code: str, start: date, end: date, *, calendar_id: str = CALENDAR_ID
) -> CalendarFunctionResult:
    """在隔离子进程中试跑指定日历函数。"""
    calendar_id = normalize_calendar_id(calendar_id)
    result = await asyncio.to_thread(run_calendar_script, code, calendar_id, start, end)
    if not result.ok:
        return _calendar_script_error(result.error or ScriptExecutionError("自定义交易日历函数执行失败"))
    try:
        entries = _ENTRY_LIST_ADAPTER.validate_python(result.value)
        _validate_calendar_function_entries(entries, calendar_id=calendar_id, start=start, end=end)
    except (ValidationError, ValueError) as exc:
        return CalendarFunctionResult(valid=False, error=str(exc), errorMessage=str(exc), errorType=type(exc).__name__)
    return CalendarFunctionResult(valid=True, entries=entries)


async def save_calendar_function(
    session: AsyncSession, *, calendar_id: str = CALENDAR_ID, function_code: str
) -> TradingCalendarConfig:
    """执行并保存 Python 刷新函数；执行失败时不改变当前日历。"""
    calendar_id = normalize_calendar_id(calendar_id)
    if not function_code.strip():
        raise ValueError("自定义交易日历函数不能为空")
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    async with lock:
        today = date.today()
        result = await run_calendar_function(
            function_code,
            today - timedelta(days=CALENDAR_INITIAL_HISTORY_DAYS),
            today + timedelta(days=CALENDAR_TARGET_FUTURE_DAYS),
            calendar_id=calendar_id,
        )
        if not result.valid:
            raise ValueError(result.error or "自定义交易日历函数执行失败")
        await _replace_calendar(session, result.entries, refresh_kind="python", function_code=function_code)
    return cast(TradingCalendarConfig, await session.get(TradingCalendarConfig, calendar_id))


async def set_calendar_overrides(session: AsyncSession, entries: list[CalendarOverrideInput]) -> None:
    """保存人工调整，且不触碰基础日历。"""
    if not entries:
        return
    statement = sqlite_insert(TradingCalendarOverride).values(
        [
            {
                "calendar_id": normalize_calendar_id(entry.calendar_id),
                "cal_date": entry.cal_date,
                "is_open": entry.is_open,
                "updated_at": now_str(),
            }
            for entry in entries
        ]
    )
    statement = statement.on_conflict_do_update(
        index_elements=["calendar_id", "cal_date"],
        set_={"is_open": statement.excluded.is_open, "updated_at": statement.excluded.updated_at},
    )
    await session.execute(statement)
    await session.commit()


async def clear_calendar_overrides(session: AsyncSession, dates: list[date], *, calendar_id: str = CALENDAR_ID) -> None:
    """恢复指定日期到基础值。"""
    if not dates:
        return
    await session.execute(
        delete(TradingCalendarOverride).where(
            col(TradingCalendarOverride.calendar_id) == normalize_calendar_id(calendar_id),
            col(TradingCalendarOverride.cal_date).in_(dates),
        )
    )
    await session.commit()


async def list_calendar_overrides(
    session: AsyncSession, *, calendar_id: str = CALENDAR_ID
) -> list[CalendarOverrideEntry]:
    """返回人工调整及当前基础值。"""
    calendar_id = normalize_calendar_id(calendar_id)
    overrides = list(
        (
            await session.execute(
                select(TradingCalendarOverride)
                .where(col(TradingCalendarOverride.calendar_id) == calendar_id)
                .order_by(col(TradingCalendarOverride.cal_date).desc())
            )
        ).scalars()
    )
    if not overrides:
        return []
    rows = (
        await session.execute(
            select(TradingCalendarRecord).where(
                col(TradingCalendarRecord.calendar_id) == calendar_id,
                col(TradingCalendarRecord.cal_date).in_([item.cal_date for item in overrides]),
            )
        )
    ).scalars()
    base = {row.cal_date: row.is_open for row in rows}
    return [
        CalendarOverrideEntry(
            calendarId=calendar_id,
            calDate=item.cal_date,
            isOpen=item.is_open,
            baseIsOpen=base.get(item.cal_date),
            updatedAt=item.updated_at,
        )
        for item in overrides
    ]


async def get_calendar_status(session: AsyncSession, calendar_id: str = CALENDAR_ID) -> CalendarStatus:
    """汇总一份日历的覆盖与同步状态。"""
    calendar_id = normalize_calendar_id(calendar_id)
    config = await session.get(TradingCalendarConfig, calendar_id)
    coverage_start, coverage_end, total = (
        await session.execute(
            select(
                func.min(col(TradingCalendarRecord.cal_date)),
                func.max(col(TradingCalendarRecord.cal_date)),
                func.count(),
            ).where(col(TradingCalendarRecord.calendar_id) == calendar_id)
        )
    ).one()
    today = date.today()
    diagnostics = await list_calendar_diagnostics(session, calendar_id=calendar_id, start=today, end=today)
    override_count = await session.scalar(
        select(func.count())
        .select_from(TradingCalendarOverride)
        .where(col(TradingCalendarOverride.calendar_id) == calendar_id)
    )
    configured = config is not None and int(total or 0) > 0
    available = diagnostics[0].is_open is not None
    return CalendarStatus(
        calendarId=calendar_id,
        availability=CalendarAvailability.AVAILABLE if available else CalendarAvailability.UNAVAILABLE,
        unavailableReason=(
            None
            if available
            else CalendarUnavailableReason.UNCOVERED
            if configured
            else CalendarUnavailableReason.NOT_CONFIGURED
        ),
        refreshKind=cast(CalendarRefreshKind | None, config.refresh_kind if config else None),
        functionCode=config.function_code if config else "",
        coverageStart=coverage_start,
        coverageEnd=coverage_end,
        overrideCount=int(override_count or 0),
        lastSyncAt=config.last_sync_at if config else None,
    )


async def _sync_one_shinny(calendar_id: str, *, force: bool) -> bool:
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    if lock.locked():
        return False
    async with lock, SessionLocal() as session:
        config = await session.get(TradingCalendarConfig, calendar_id)
        if config is None or config.refresh_kind != SHINNY_CALENDAR_REFRESH_KIND:
            return False
        today = date.today()
        last_supported_day = date(SHINNY_CALENDAR_LAST_YEAR, 12, 31)
        if today > last_supported_day:
            logger.warning("Shinny 交易日历仅覆盖至 {}，不再刷新 {}", last_supported_day, calendar_id)
            return False
        covered_end = min(today + timedelta(days=CALENDAR_MIN_FUTURE_DAYS), last_supported_day)
        covered = await session.scalar(
            select(func.count())
            .select_from(TradingCalendarRecord)
            .where(
                col(TradingCalendarRecord.calendar_id) == calendar_id,
                col(TradingCalendarRecord.cal_date) >= today,
                col(TradingCalendarRecord.cal_date) <= covered_end,
            )
        )
        if not force and int(covered or 0) == (covered_end - today).days + 1:
            return False
        try:
            await _save_shinny_calendar(
                session,
                calendar_id=calendar_id,
                start=today - timedelta(days=CALENDAR_INITIAL_HISTORY_DAYS),
                end=today + timedelta(days=CALENDAR_TARGET_FUTURE_DAYS),
            )
        except Exception as exc:  # noqa: BLE001 - 刷新失败保留旧日历
            logger.error("刷新 {} Shinny 交易日历失败，保留现有数据: {}", calendar_id, type(exc).__name__)
            return False
        logger.info("已刷新 {} Shinny 交易日历", calendar_id)
        return True


async def _sync_one_tushare(calendar_id: str, *, force: bool) -> bool:
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    if lock.locked():
        return False
    async with lock, SessionLocal() as session:
        config = await session.get(TradingCalendarConfig, calendar_id)
        if config is None or config.refresh_kind != TUSHARE_CALENDAR_REFRESH_KIND:
            return False
        today = date.today()
        covered = await session.scalar(
            select(func.count())
            .select_from(TradingCalendarRecord)
            .where(
                col(TradingCalendarRecord.calendar_id) == calendar_id,
                col(TradingCalendarRecord.cal_date) >= today,
                col(TradingCalendarRecord.cal_date) <= today + timedelta(days=CALENDAR_MIN_FUTURE_DAYS),
            )
        )
        if not force and int(covered or 0) == CALENDAR_MIN_FUTURE_DAYS + 1:
            return False
        try:
            await _save_tushare_calendar(
                session,
                calendar_id=calendar_id,
                start=today - timedelta(days=CALENDAR_INITIAL_HISTORY_DAYS),
                end=today + timedelta(days=CALENDAR_TARGET_FUTURE_DAYS),
            )
        except Exception as exc:  # noqa: BLE001 - 刷新失败保留旧日历
            logger.error("刷新 {} Tushare 交易日历失败，保留现有数据: {}", calendar_id, type(exc).__name__)
            return False
        logger.info("已刷新 {} Tushare 交易日历", calendar_id)
        return True


async def _sync_one_python(calendar_id: str, *, force: bool) -> bool:
    lock = _SYNC_LOCKS.setdefault(calendar_id, asyncio.Lock())
    if lock.locked():
        return False
    async with lock, SessionLocal() as session:
        config = await session.get(TradingCalendarConfig, calendar_id)
        if config is None or config.refresh_kind != "python" or not config.function_code.strip():
            return False
        today = date.today()
        if not force:
            covered = await session.scalar(
                select(func.count())
                .select_from(TradingCalendarRecord)
                .where(
                    col(TradingCalendarRecord.calendar_id) == calendar_id,
                    col(TradingCalendarRecord.cal_date) >= today,
                    col(TradingCalendarRecord.cal_date) <= today + timedelta(days=CALENDAR_MIN_FUTURE_DAYS),
                )
            )
            if int(covered or 0) == CALENDAR_MIN_FUTURE_DAYS + 1:
                return False
        result = await run_calendar_function(
            config.function_code,
            today - timedelta(days=CALENDAR_INITIAL_HISTORY_DAYS),
            today + timedelta(days=CALENDAR_TARGET_FUTURE_DAYS),
            calendar_id=calendar_id,
        )
        if not result.valid:
            logger.error("刷新 {} Python 交易日历失败，保留现有数据: {}", calendar_id, result.error)
            return False
        await _replace_calendar(session, result.entries, refresh_kind="python", function_code=config.function_code)
        logger.info("已刷新 {} Python 交易日历，共 {} 条", calendar_id, len(result.entries))
        return True


async def sync_calendar_shinny(*, calendar_id: str | None = None, force: bool = False) -> bool:
    """刷新一个或全部配置为 Shinny 的中国期货兜底日历。"""
    if calendar_id is not None:
        return await _sync_one_shinny(normalize_calendar_id(calendar_id), force=force)
    async with SessionLocal() as session:
        rows = await session.execute(
            select(TradingCalendarConfig.calendar_id).where(
                col(TradingCalendarConfig.refresh_kind) == SHINNY_CALENDAR_REFRESH_KIND
            )
        )
        calendar_ids = list(rows.scalars().all())
    results = await asyncio.gather(*(_sync_one_shinny(item, force=force) for item in calendar_ids))
    return any(results)


async def sync_calendar_tushare(*, calendar_id: str | None = None, force: bool = False) -> bool:
    """刷新一个或全部配置为 Tushare 的日历。"""
    if calendar_id is not None:
        return await _sync_one_tushare(normalize_calendar_id(calendar_id), force=force)
    async with SessionLocal() as session:
        rows = await session.execute(
            select(TradingCalendarConfig.calendar_id).where(
                col(TradingCalendarConfig.refresh_kind) == TUSHARE_CALENDAR_REFRESH_KIND
            )
        )
        calendar_ids = list(rows.scalars().all())
    results = await asyncio.gather(*(_sync_one_tushare(item, force=force) for item in calendar_ids))
    return any(results)


async def sync_calendar_python(*, calendar_id: str | None = None, force: bool = False) -> bool:
    """刷新一个或全部配置为 Python 的日历。"""
    if calendar_id is not None:
        return await _sync_one_python(normalize_calendar_id(calendar_id), force=force)
    async with SessionLocal() as session:
        rows = await session.execute(
            select(TradingCalendarConfig.calendar_id).where(
                col(TradingCalendarConfig.refresh_kind) == "python",
                col(TradingCalendarConfig.function_code) != "",
            )
        )
        calendar_ids = list(rows.scalars().all())
    results = await asyncio.gather(*(_sync_one_python(item, force=force) for item in calendar_ids))
    return any(results)


async def ensure_trading_calendar_coverage() -> None:
    """定时检查全部自动刷新日历的未来覆盖。"""
    await asyncio.gather(
        sync_calendar_python(force=False),
        sync_calendar_shinny(force=False),
        sync_calendar_tushare(force=False),
    )


def register_trading_calendar_job(scheduler: Scheduler) -> None:
    """注册每日一次的交易日历覆盖检查。"""
    scheduler.add_job(
        ensure_trading_calendar_coverage,
        trigger="cron",
        hour=4,
        minute=0,
        id=CALENDAR_JOB_ID,
        replace_existing=True,
    )


__all__ = [
    "CALENDAR_ID",
    "CalendarAvailability",
    "CalendarDayDecision",
    "CalendarDecisionStatus",
    "CalendarDiagnosticEntry",
    "CalendarFunctionResult",
    "CalendarImportPreview",
    "CalendarInputEntry",
    "CalendarOverrideEntry",
    "CalendarOverrideInput",
    "CalendarStatus",
    "CalendarUnavailableReason",
    "TradingCalendarEntry",
    "build_import_preview",
    "apply_pending_initial_calendars",
    "clear_calendar_overrides",
    "ensure_trading_calendar_coverage",
    "evaluate_channel_calendar_day",
    "evaluate_channel_calendar_days",
    "evaluate_channel_calendar_moment",
    "get_calendar_status",
    "import_calendar_csv",
    "list_calendar_diagnostics",
    "list_calendar_entries",
    "list_calendar_overrides",
    "normalize_calendar_id",
    "parse_calendar_csv",
    "register_trading_calendar_job",
    "run_calendar_function",
    "save_calendar_function",
    "save_shinny_calendar",
    "save_tushare_calendar",
    "set_calendar_overrides",
    "stage_initial_calendars",
    "sync_calendar_python",
    "sync_calendar_shinny",
    "sync_calendar_tushare",
    "validate_calendar_entries",
]

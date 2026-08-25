"""OpenCTP 品种交易时段快照刷新。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from axile.executor.algorithms.utils import clock_now
from axile.server.core.db import SessionLocal
from axile.server.core.scheduler import Scheduler
from axile.server.db.models import CtpSessionSnapshot, CtpSessionSnapshotRecord

_OPENCTP_TIMES_URL = "http://dict.openctp.cn/times?types=futures"
_HTTP_TIMEOUT_SECONDS = 10
_SHANGHAI = ZoneInfo("Asia/Shanghai")
CTP_SESSION_SNAPSHOT_JOB_ID = "refresh-ctp-session-snapshot"
_SNAPSHOT_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class OpenCtpProductSession:
    """经过响应校验的 OpenCTP 品种时段行。"""

    exchange_id: str
    product_id: str
    segment_no: int
    time_begin: time
    time_end: time


def parse_openctp_product_sessions(payload: object) -> list[OpenCtpProductSession]:
    """校验并规范化 OpenCTP futures 时段响应。"""
    if not isinstance(payload, dict):
        raise ValueError("OpenCTP 时段响应必须是对象")
    if payload.get("rsp_code") != 0:
        raise ValueError(f"OpenCTP 时段响应 rsp_code 无效: {payload.get('rsp_code')}")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("OpenCTP 时段响应缺少 data")

    entries: list[OpenCtpProductSession] = []
    keys: set[tuple[str, str, int]] = set()
    for raw in data:
        if not isinstance(raw, dict):
            raise ValueError("OpenCTP 时段行必须是对象")
        try:
            exchange_id = _required_text(raw, "ExchangeID")
            product_id = _required_text(raw, "ProductID")
            segment_no = int(raw["SegmentNo"])
            time_begin = time.fromisoformat(_required_text(raw, "TimeBegin"))
            time_end = time.fromisoformat(_required_text(raw, "TimeEnd"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"OpenCTP 时段行无效: {exc}") from exc
        if segment_no < 1:
            raise ValueError("OpenCTP 时段行 SegmentNo 必须为正整数")
        key = (exchange_id, product_id, segment_no)
        if key in keys:
            raise ValueError(f"OpenCTP 时段响应存在重复记录: {key}")
        keys.add(key)
        entries.append(OpenCtpProductSession(exchange_id, product_id, segment_no, time_begin, time_end))
    return sorted(entries, key=lambda item: (item.exchange_id, item.product_id, item.segment_no))


async def fetch_openctp_product_sessions() -> list[OpenCtpProductSession]:
    """从 OpenCTP 拉取 futures 品种时段；仅供后台刷新任务调用。"""
    timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as client, client.get(_OPENCTP_TIMES_URL) as response:
        if response.status != 200:
            raise RuntimeError(f"OpenCTP 时段请求失败: HTTP {response.status}")
        return parse_openctp_product_sessions(await response.json(content_type=None))


async def replace_ctp_session_snapshot(
    session: AsyncSession,
    entries: list[OpenCtpProductSession],
    *,
    fetched_at: str,
    snapshot_id: str,
) -> None:
    """在单一事务内写入完整快照并切换活动指针。"""
    if not entries:
        raise ValueError("CTP 时段快照不能为空")
    try:
        await session.execute(
            CtpSessionSnapshot.__table__.update().where(CtpSessionSnapshot.is_active.is_(True)).values(is_active=False)
        )
        session.add(CtpSessionSnapshot(snapshot_id=snapshot_id, fetched_at=fetched_at, is_active=True))
        session.add_all(
            [
                CtpSessionSnapshotRecord(
                    snapshot_id=snapshot_id,
                    exchange_id=entry.exchange_id,
                    product_id=entry.product_id,
                    segment_no=entry.segment_no,
                    time_begin=entry.time_begin.isoformat(),
                    time_end=entry.time_end.isoformat(),
                )
                for entry in entries
            ]
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def refresh_ctp_session_snapshot() -> bool:
    """刷新本地完整快照；失败时保留最后可用快照。"""
    if _SNAPSHOT_LOCK.locked():
        return False
    async with _SNAPSHOT_LOCK:
        try:
            entries = await fetch_openctp_product_sessions()
            async with SessionLocal() as session:
                await replace_ctp_session_snapshot(
                    session,
                    entries,
                    fetched_at=clock_now(tz=_SHANGHAI).isoformat(),
                    snapshot_id=uuid.uuid4().hex,
                )
        except Exception as exc:  # noqa: BLE001 - 刷新失败不能清空最后完整快照
            logger.error("刷新 CTP 品种时段快照失败，保留现有快照: {}", exc)
            return False
        logger.info("已刷新 CTP 品种时段快照，共 {} 条", len(entries))
        return True


async def ensure_ctp_session_snapshot() -> None:
    """按日刷新 CTP 时段本地快照。"""
    await refresh_ctp_session_snapshot()


def register_ctp_session_snapshot_job(scheduler: Scheduler) -> None:
    """注册每日一次的 CTP 时段快照刷新任务。"""
    scheduler.add_job(
        ensure_ctp_session_snapshot,
        trigger="cron",
        hour=4,
        minute=10,
        id=CTP_SESSION_SNAPSHOT_JOB_ID,
        replace_existing=True,
    )


def _required_text(row: dict[str, Any], key: str) -> str:
    value = row[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 不能为空")
    return value.strip()


__all__ = [
    "CTP_SESSION_SNAPSHOT_JOB_ID",
    "OpenCtpProductSession",
    "ensure_ctp_session_snapshot",
    "fetch_openctp_product_sessions",
    "parse_openctp_product_sessions",
    "refresh_ctp_session_snapshot",
    "register_ctp_session_snapshot_job",
    "replace_ctp_session_snapshot",
]

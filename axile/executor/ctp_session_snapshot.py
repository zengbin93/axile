"""CTP 执行路径使用的本地品种时段快照读取器。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from sqlalchemy.engine import make_url

from axile.executor.algorithms.utils import clock_now
from axile.executor.ctp_product_sessions import CtpProductSession

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_STALE_AFTER = timedelta(hours=168)
_WARN_AFTER = timedelta(hours=120)


@dataclass(frozen=True)
class CtpSessionSnapshotResult:
    """一次本地快照读取结果。"""

    sessions: tuple[CtpProductSession, ...]
    reason_code: str | None = None
    warning: bool = False


class CtpSessionSnapshotReader(Protocol):
    """读取当前活动 CTP 品种时段快照。"""

    def get_sessions(
        self,
        exchange_id: str,
        product_id: str,
        *,
        now: datetime | None = None,
    ) -> CtpSessionSnapshotResult:
        """返回指定交易所与品种的当前可用时段。"""
        ...


class SqliteCtpSessionSnapshot:
    """同步读取 SQLite 中当前活动的完整 CTP 时段快照。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    @classmethod
    def from_database_uri(cls, database_uri: str) -> "SqliteCtpSessionSnapshot":
        """从 SQLAlchemy SQLite URI 创建读取器。"""
        url = make_url(database_uri)
        if not url.drivername.startswith("sqlite") or not url.database:
            raise ValueError("CTP 时段快照只支持 SQLite 数据库")
        return cls(Path(url.database).expanduser().resolve())

    def get_sessions(
        self,
        exchange_id: str,
        product_id: str,
        *,
        now: datetime | None = None,
    ) -> CtpSessionSnapshotResult:
        """读取活动快照并按时效返回指定品种时段。"""
        current = now or clock_now(tz=_SHANGHAI)
        try:
            with sqlite3.connect(self._database_path, timeout=1) as connection:
                snapshot = cast(
                    "tuple[str, str] | None",
                    connection.execute(
                        "SELECT snapshot_id, fetched_at FROM ctp_session_snapshot WHERE is_active = 1"
                    ).fetchone(),
                )
                if snapshot is None:
                    return CtpSessionSnapshotResult((), "CTP.SESSION.SNAPSHOT_MISSING")
                snapshot_id, fetched_at = snapshot
                age = current - _parse_shanghai_datetime(fetched_at)
                if age >= _STALE_AFTER:
                    return CtpSessionSnapshotResult((), "CTP.SESSION.SNAPSHOT_STALE")
                rows = connection.execute(
                    """
                    SELECT exchange_id, product_id, segment_no, time_begin, time_end
                    FROM ctp_session_snapshot_record
                    WHERE snapshot_id = ? AND exchange_id = ? AND product_id = ?
                    ORDER BY segment_no
                    """,
                    (snapshot_id, exchange_id, product_id),
                ).fetchall()
        except sqlite3.Error:
            return CtpSessionSnapshotResult((), "CTP.SESSION.SNAPSHOT_MISSING")

        sessions = tuple(
            CtpProductSession(
                exchange_id=str(row[0]),
                product_id=str(row[1]),
                segment_no=int(row[2]),
                time_begin=time.fromisoformat(str(row[3])),
                time_end=time.fromisoformat(str(row[4])),
            )
            for row in rows
        )
        if not sessions:
            return CtpSessionSnapshotResult((), "CTP.SESSION.SNAPSHOT_MISSING")
        return CtpSessionSnapshotResult(sessions, warning=age >= _WARN_AFTER)


def _parse_shanghai_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=_SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(_SHANGHAI)


__all__ = ["CtpSessionSnapshotReader", "CtpSessionSnapshotResult", "SqliteCtpSessionSnapshot"]

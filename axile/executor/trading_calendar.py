"""执行器使用的本地交易日历查询接口。"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy.engine import make_url


class TradingCalendar(Protocol):
    """定义执行器所需的最小交易日历能力。"""

    def is_open(self, calendar_id: str, day: date) -> bool | None:
        """返回开闭市状态；本地无记录时返回 ``None``。"""


class SqliteTradingCalendar:
    """从 Axile SQLite 数据库同步读取交易日历。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path: Path = database_path

    @classmethod
    def from_database_uri(cls, database_uri: str) -> "SqliteTradingCalendar":
        """从 SQLAlchemy SQLite URI 创建读取器。"""
        url = make_url(database_uri)
        if not url.drivername.startswith("sqlite") or not url.database:
            raise ValueError("交易日历只支持 SQLite 数据库")
        return cls(Path(url.database).expanduser().resolve())

    def is_open(self, calendar_id: str, day: date) -> bool | None:
        """查询指定日历和日期；无记录时返回 None。"""
        with sqlite3.connect(self._database_path, timeout=1) as connection:
            override = cast(
                "tuple[int] | None",
                connection.execute(
                    "SELECT is_open FROM trading_calendar_override WHERE calendar_id = ? AND cal_date = ?",
                    (calendar_id.lower(), day.isoformat()),
                ).fetchone(),
            )
            if override is not None:
                return bool(override[0])
            row = cast(
                "tuple[int] | None",
                connection.execute(
                    "SELECT is_open FROM trading_calendar WHERE calendar_id = ? AND cal_date = ?",
                    (calendar_id.lower(), day.isoformat()),
                ).fetchone(),
            )
        return bool(row[0]) if row is not None else None


__all__ = ["SqliteTradingCalendar", "TradingCalendar"]

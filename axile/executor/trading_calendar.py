"""执行器使用的本地交易日历查询接口。"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy.engine import make_url


class TradingCalendar(Protocol):
    """定义执行器所需的最小交易日历能力。"""

    def is_open(self, exchange: str, day: date) -> bool | None:
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

    def is_open(self, exchange: str, day: date) -> bool | None:
        """查询指定交易所和日期的开闭市状态。"""
        with sqlite3.connect(self._database_path, timeout=1) as connection:
            row = cast(
                "tuple[int] | None",
                connection.execute(
                    "SELECT is_open FROM trading_calendar WHERE exchange = ? AND cal_date = ?",
                    (exchange.upper(), day.isoformat()),
                ).fetchone(),
            )
        return None if row is None else bool(row[0])


__all__ = ["SqliteTradingCalendar", "TradingCalendar"]

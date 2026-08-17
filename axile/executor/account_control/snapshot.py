"""
提供账户控制运行时使用的内存快照类型.

Notes
-----
该模块只描述单次 execution 期间会消费的基线计数与最近放行时间，
不涉及任何数据库或持久化实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from axile.executor.account_control.models import AccountControlBucketType

AccountCounterKey: TypeAlias = tuple[AccountControlBucketType, str, str]
SymbolCounterKey: TypeAlias = tuple[str, AccountControlBucketType, str, str]
RecentAccountKey: TypeAlias = tuple[str]
RecentSymbolKey: TypeAlias = tuple[str, str]


@dataclass
class AccountControlCounterSnapshot:
    """
    表示执行开始时读取出的计数器基线.

    Attributes
    ----------
    account_counts : dict[AccountCounterKey, int]
        账户级计数器快照。
    symbol_counts : dict[SymbolCounterKey, int]
        标的级计数器快照。
    """

    account_counts: dict[AccountCounterKey, int] = field(default_factory=dict)
    symbol_counts: dict[SymbolCounterKey, int] = field(default_factory=dict)

    def add(
        self,
        *,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        operation: str,
        delta_count: int,
        symbol: str | None = None,
    ) -> None:
        """
        向快照中累加一条计数增量.

        Parameters
        ----------
        bucket_type : AccountControlBucketType
            计数所属的时间桶类型。
        bucket_start : str
            时间桶起始时间。
        operation : str
            对应的操作键。
        delta_count : int
            需要累加的计数值。
        symbol : str | None, optional
            标的代码；为空时表示账户级计数。
        """
        if symbol is None:
            key = (bucket_type, bucket_start, operation)
            self.account_counts[key] = self.account_counts.get(key, 0) + delta_count
            return

        key = (symbol, bucket_type, bucket_start, operation)
        self.symbol_counts[key] = self.symbol_counts.get(key, 0) + delta_count

    def get_count(
        self,
        *,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        operation: str,
        symbol: str | None = None,
    ) -> int:
        """
        获取指定维度下的当前计数值.

        Parameters
        ----------
        bucket_type : AccountControlBucketType
            计数所属的时间桶类型。
        bucket_start : str
            时间桶起始时间。
        operation : str
            对应的操作键。
        symbol : str | None, optional
            标的代码；为空时查询账户级计数。

        Returns
        -------
        int
            命中维度的累计计数值；未命中时返回 ``0``。
        """
        if symbol is None:
            return self.account_counts.get((bucket_type, bucket_start, operation), 0)
        return self.symbol_counts.get((symbol, bucket_type, bucket_start, operation), 0)


@dataclass
class AccountControlRecentAllowedSnapshot:
    """
    表示最近一次放行时间的快照.

    Attributes
    ----------
    account_timestamps : dict[RecentAccountKey, int]
        账户级最近放行时间戳。
    symbol_timestamps : dict[RecentSymbolKey, int]
        标的级最近放行时间戳。
    """

    account_timestamps: dict[RecentAccountKey, int] = field(default_factory=dict)
    symbol_timestamps: dict[RecentSymbolKey, int] = field(default_factory=dict)

    def add(self, *, operation: str, occurred_at_ms: int, symbol: str | None = None) -> None:
        """
        记录一次最近放行时间.

        Parameters
        ----------
        operation : str
            对应的操作键。
        occurred_at_ms : int
            放行事件发生的毫秒时间戳。
        symbol : str | None, optional
            标的代码；为空时表示账户级记录。
        """
        if symbol is None:
            key = (operation,)
            self.account_timestamps[key] = max(self.account_timestamps.get(key, occurred_at_ms), occurred_at_ms)
            return

        key = (symbol, operation)
        self.symbol_timestamps[key] = max(self.symbol_timestamps.get(key, occurred_at_ms), occurred_at_ms)

    def get_last_allowed_at_ms(
        self,
        operation: str,
        *,
        symbol: str | None = None,
    ) -> int | None:
        """
        获取最近一次放行时间.

        Parameters
        ----------
        operation : str
            对应的操作键。
        symbol : str | None, optional
            标的代码；为空时查询账户级记录。

        Returns
        -------
        int | None
            最近一次放行的毫秒时间戳；未命中时返回 ``None``。
        """
        if symbol is None:
            return self.account_timestamps.get((operation,))
        return self.symbol_timestamps.get((symbol, operation))

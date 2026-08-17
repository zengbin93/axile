"""
账户当日分析器.

提供账户当日执行记录的各种分析功能，包括：
- 收益率计算
- 风险指标（最大回撤、杠杆倍数）
- 持仓分析（多头、空头、净市值）
- 资金状况（可用余额、保证金占用等）
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlmodel import and_, desc, select

from axile.server.api.deps import SessionDep
from axile.server.db.models import ExecuteRecord


class Context:
    """
    提供账户当日执行上下文分析的辅助对象。

    Notes
    -----
    该对象会懒加载当天执行记录、上一交易日最后一条基准记录和最新账户资产快照，
    避免同一份分析报表在多个指标之间重复访问数据库。
    """

    session: SessionDep
    account_id: int
    _records: list[ExecuteRecord] | None
    _latest_record: ExecuteRecord | None
    _account_assets: dict[str, object] | None

    def __init__(self, session: SessionDep, account_id: int) -> None:
        """
        初始化账户分析上下文。

        Parameters
        ----------
        session : SessionDep
            数据库会话依赖。
        account_id : int
            账户标识。
        """
        self.session = session
        self.account_id = account_id
        self._records = None
        self._latest_record = None
        self._yesterday_last = None
        self._account_assets = None

    def _get_previous_last_record(self) -> ExecuteRecord | None:
        """
        查询今天之前的最后一条成功执行记录.

        Returns
        -------
        ExecuteRecord | None
            前一天的最后一条成功执行记录；不存在时返回 ``None``。
        """
        day_start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%dT00:00:00")
        day_end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT23:59:59")

        conditions = [
            ExecuteRecord.account_id == self.account_id,
            ExecuteRecord.created_at >= day_start,
            ExecuteRecord.created_at <= day_end,
            ExecuteRecord.is_success == 1,
        ]

        async def _query() -> ExecuteRecord | None:
            result = await self.session.execute(
                select(ExecuteRecord).where(and_(*conditions)).order_by(desc(ExecuteRecord.created_at)).limit(1)
            )
            return result.scalar_one_or_none()

        self._yesterday_last = asyncio.run(_query())
        return self._yesterday_last

    def _load_records(self, only_success: bool = True) -> list[ExecuteRecord]:
        """懒加载所需要的执行记录."""
        if self._records is None:
            today = datetime.now().strftime("%Y-%m-%d")
            # ISO 8601 格式可以直接进行字符串比较
            day_start = f"{today}T00:00:00"
            day_end = f"{today}T23:59:59"

            conditions = [
                ExecuteRecord.account_id == self.account_id,
                ExecuteRecord.created_at >= day_start,
                ExecuteRecord.created_at <= day_end,
            ]

            if only_success:
                conditions.append(ExecuteRecord.is_success == 1)

            async def _query() -> list[ExecuteRecord]:
                result = await self.session.execute(
                    select(ExecuteRecord).where(and_(*conditions)).order_by(ExecuteRecord.created_at)
                )
                return list(result.scalars().all())

            today_records = asyncio.run(_query())
            previous_last = self._get_previous_last_record()

            if previous_last:
                # 这里刻意把“上一交易日最后一条成功记录”拼到当天序列前面，后续收益率、
                # 回撤和资金变化分析都需要这条基准线，而不只是今天的增量记录。
                self._records = [previous_last] + today_records
            else:
                self._records = today_records

        return self._records

    def _get_latest_record(self) -> ExecuteRecord | None:
        """获取最新执行记录."""
        if self._latest_record is None:
            records = self._load_records()
            self._latest_record = records[-1] if records else None

        return self._latest_record

    def _get_account_assets(self) -> dict[str, object]:
        """获取最新账户资产数据."""
        if self._account_assets is None:
            latest_record = self._get_latest_record()
            if latest_record:
                self._account_assets = latest_record.raw_result.get("account_assets", {}) or {}
            else:
                self._account_assets = {}

        return self._account_assets  # type: ignore

    def has_data(self) -> bool:
        """
        检查是否有数据（当天数据或前一天基准数据）.

        Returns
        -------
            bool: 如果有当天执行记录或前一天基准记录则返回True
        """
        records = self._load_records()
        return len(records) > 0

    def get_execution_count(self) -> int:
        """获取当日执行次数."""
        records = self._load_records()
        return len(records)

    @property
    def today_return(self) -> float:
        """
        计算当日收益率.

        Returns
        -------
        float
            当日收益率，小数形式 ``0.025`` 表示 ``2.5%``。
        """
        records = self._load_records()

        if not records:
            return 0.0

        first_total = Decimal(
            str(records[0].raw_result.get("account_assets", {}).get("total_asset", 0))  # type: ignore
        )
        last_total = Decimal(
            str(records[-1].raw_result.get("account_assets", {}).get("total_asset", 0))  # type: ignore
        )

        if first_total == 0:
            return 0.0

        # 如果只有一条记录且是前一天的基准记录，当日收益率为0
        if len(records) == 1:
            # 检查这条记录是否是前一天的记录
            record_date = records[0].created_at[:10]  # 获取日期部分 (YYYY-MM-DD)
            today = datetime.now().strftime("%Y-%m-%d")
            if record_date != today:
                return 0.0

        return float((last_total - first_total) / first_total)

    @property
    def today_max_drawdown(self) -> float:
        """
        计算当日最大回撤.

        Returns
        -------
            float: 当日最大回撤（小数形式，如 0.05 表示 5%）
        """
        records = self._load_records()

        if len(records) < 2:
            return 0.0

        max_drawdown = 0.0
        peak_value = Decimal("0")

        for record in records:
            total_asset = Decimal(
                str(record.raw_result.get("account_assets", {}).get("total_asset", 0))  # type: ignore
            )

            if total_asset > peak_value:
                peak_value = total_asset

            if peak_value > 0:
                current_drawdown = float((peak_value - total_asset) / peak_value)
                max_drawdown = max(max_drawdown, current_drawdown)

        return max_drawdown

    # ==================== 杠杆分析方法 ====================

    @property
    def current_leverage(self) -> float:
        """
        计算当前杠杆倍数.

        Returns
        -------
            float: 当前杠杆倍数（总持仓市值 / 账户总余额）
        """
        account_assets = self._get_account_assets()

        if not account_assets:
            return 0.0

        market_value = Decimal(str(account_assets.get("market_value", 0)))  # type: ignore
        total_asset = Decimal(str(account_assets.get("total_asset", 0)))  # type: ignore

        if total_asset == 0:
            return 0.0

        return float(market_value / total_asset)

    # ==================== 持仓分析方法 ====================

    @property
    def long_market_value(self) -> float:
        """计算多头市值."""
        account_assets = self._get_account_assets()
        positions = cast("list[dict[str, object]]", account_assets.get("positions", []))

        long_value = Decimal("0")
        for position in positions:
            if isinstance(position, dict) and position.get("direction") == "多头":  # type: ignore
                long_value += Decimal(str(position.get("market_value", 0)))  # type: ignore

        return float(long_value)

    @property
    def short_market_value(self) -> float:
        """计算空头市值."""
        account_assets = self._get_account_assets()
        positions = cast("list[dict[str, object]]", account_assets.get("positions", []))

        short_value = Decimal("0")
        for position in positions:
            if isinstance(position, dict) and position.get("direction") == "空头":  # type: ignore
                short_value += Decimal(str(position.get("market_value", 0)))  # type: ignore

        return float(short_value)

    @property
    def net_market_value(self) -> float:
        """计算净市值（多头市值 - 空头市值）."""
        long_value = self.long_market_value
        short_value = self.short_market_value

        return long_value - short_value

    # ==================== 资金状况分析方法 ====================

    @property
    def yesterday_total_balance(self) -> float:
        """
        计算昨日总余额.

        Returns
        -------
            float: 昨日总余额（基于前一天最后一条成功执行记录）
        """
        if self._yesterday_last is None:
            self._get_previous_last_record()

        if self._yesterday_last is None:
            return 0.0

        yesterday_assets = self._yesterday_last.raw_result.get("account_assets", {})
        yesterday_total = yesterday_assets.get("total_asset", 0)

        return float(Decimal(str(yesterday_total)))

    @property
    def available_balance(self) -> float:
        """计算可用余额."""
        account_assets = self._get_account_assets()
        available_cash = account_assets.get("available_cash", 0)  # type: ignore
        return float(Decimal(str(available_cash)))

    @property
    def frozen_funds(self) -> float:
        """计算冻结资金."""
        account_assets = self._get_account_assets()

        total_asset = Decimal(str(account_assets.get("total_asset", 0)))  # type: ignore
        available_cash = Decimal(str(account_assets.get("available_cash", 0)))  # type: ignore

        return float(total_asset - available_cash)

    @property
    def total_balance(self) -> float:
        """计算账户总余额."""
        account_assets = self._get_account_assets()
        total_asset = account_assets.get("total_asset", 0)  # type: ignore
        return float(Decimal(str(total_asset)))

    @property
    def used_margin(self) -> float:
        """计算已用保证金."""
        return self.frozen_funds

    @property
    def margin_usage_ratio(self) -> float:
        """计算保证金占用比例."""
        account_assets = self._get_account_assets()

        total_asset = Decimal(str(account_assets.get("total_asset", 0)))  # type: ignore
        available_cash = Decimal(str(account_assets.get("available_cash", 0)))  # type: ignore

        if total_asset == 0:
            return 0.0

        return float((total_asset - available_cash) / total_asset)

    @property
    def consecutive_loss_days(self) -> int:
        """
        计算连续亏损天数.

        Returns
        -------
            int: 连续亏损天数
        """

        async def _query() -> int:
            # 查询每日总资产，按日期分组，取每天最后一条记录
            query = """
            SELECT
                DATE(created_at) as date,
                json_extract(raw_result, '$.account_assets.total_asset') as total_asset
            FROM executerecord
            WHERE account_id = :account_id AND is_success = 1
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) DESC
            """

            from sqlalchemy import text

            result = await self.session.execute(text(query), {"account_id": self.account_id})
            rows = result.fetchall()
            daily_data = [{"date": row[0], "total_asset": row[1]} for row in rows]

            if not daily_data:
                return 0

            # 计算每日收益率
            daily_returns: list[dict[str, Any]] = []
            for i in range(len(daily_data) - 1):
                current_total = Decimal(str(daily_data[i]["total_asset"] or 0))
                previous_total = Decimal(str(daily_data[i + 1]["total_asset"] or 0))

                if previous_total > 0:
                    daily_return = float((current_total - previous_total) / previous_total)
                    daily_returns.append({"date": daily_data[i]["date"], "return": daily_return})

            if not daily_returns:
                return 0

            # 计算连续亏损天数
            consecutive_days = 0

            for day_data in daily_returns:
                if day_data["return"] < 0:
                    consecutive_days += 1
                else:
                    break  # 遇到盈利日就停止

            return consecutive_days

        return asyncio.run(_query())

    @property
    def last_update_time(self) -> str | None:
        """
        计算最后更新时间.

        Returns
        -------
            str | None: 最后更新时间（ISO 8601格式），如果没有记录则返回None
        """

        async def _query() -> str | None:
            # 查询最新的执行记录时间
            query = """
            SELECT created_at
            FROM executerecord
            WHERE account_id = :account_id AND is_success = 1
            ORDER BY created_at DESC
            LIMIT 1
            """

            from sqlalchemy import text

            result = await self.session.execute(text(query), {"account_id": self.account_id})
            row = result.fetchone()
            return row[0] if row else None

        return asyncio.run(_query())


class SampleContext:
    """
    dry-run 验证用的样例上下文.

    字段与 :class:`Context` 对外暴露的属性一一对齐, 但取值为固定的合理假值,
    不访问数据库。用于「Dry-run 验证」自定义组合脚本时提供一个可用的 ``context``,
    使脚本在不绑定真实账户的情况下也能跑通并返回权重。

    Notes
    -----
    :func:`invoke_portfolio_calc_code` 对 ``context`` 只做属性访问、原样透传给用户
    的 ``calculate_portfolio(context)``, 因此这里用一个鸭子类型对象即可, 无需继承
    :class:`Context`, 从而彻底绕开 ``consecutive_loss_days`` / ``last_update_time``
    等强依赖数据库会话的属性。
    """

    def __init__(self) -> None:
        """使用一组固定的合理假值初始化各字段."""
        self.today_return: float = 0.012
        self.today_max_drawdown: float = 0.035
        self.current_leverage: float = 1.8
        self.long_market_value: float = 60000.0
        self.short_market_value: float = 20000.0
        self.net_market_value: float = 40000.0
        self.yesterday_total_balance: float = 100000.0
        self.available_balance: float = 45000.0
        self.frozen_funds: float = 55000.0
        self.total_balance: float = 100000.0
        self.used_margin: float = 55000.0
        self.margin_usage_ratio: float = 0.55
        self.consecutive_loss_days: int = 0
        self.last_update_time: str = "2026-07-13T09:30:00"


def build_sample_context() -> SampleContext:
    """
    构造一个 dry-run 验证用的样例上下文.

    Returns
    -------
    SampleContext
        字段齐全、取值为固定假值、不触达数据库的样例上下文对象。
    """
    return SampleContext()

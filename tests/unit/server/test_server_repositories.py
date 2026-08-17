"""基于内存异步 SQLite 数据库的仓储辅助函数测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from axile.common.trade_channel import TradeChannel
from axile.domain.strategy import Strategy
from axile.server.db.models import Account, ExecuteRecord, Portfolio, PortfolioAccount, StrategyConfig
from axile.server.repositories import (
    add_strategies_by_portfolio_id,
    get_latest_strategies_by_account_id,
    get_portfolio_strategies_and_account,
    get_portfolios_every_account,
    get_recent_execute_records_by_account_id,
)


def _strategy(name: str, weight: float) -> Strategy:
    return Strategy(name=name, weight=weight)


def _build_portfolio(name: str) -> Portfolio:
    return Portfolio(
        name=name,
        market="加密货币",
        description=None,
        custom_calc_py_code=None,
        status=None,
        tag=None,
    )


def _build_account(name: str, portfolio_id: int | None = None) -> Account:
    return Account(
        name=name,
        market="加密货币",
        trade_channel=TradeChannel.CTP,
        account_control_preset="default",
        account_control_override=None,
        account_config={"api_key": "key", "secret_key": "secret", "is_testnet": True},
        is_started=True,
        cron_expr="*/5 * * * *",
        remark=None,
        brokerage="ctp",
        weight_precision=0.001,
        long_leverage=1.0,
        short_leverage=1.0,
        algorithm={"method": "SINGLE-MAKER"},
        trade_rules={},
        forbidden_symbols=[],
        risk_symbols=[],
        feishu_key=None,
        portfolio_id=portfolio_id,
    )


@asynccontextmanager
async def _session_scope() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def test_add_strategies_by_portfolio_id_creates_and_adds_strategy_config() -> None:
    """创建一条 StrategyConfig 记录并加入会话。"""
    session = MagicMock()
    strategies = [_strategy("alpha", 0.6), _strategy("beta", 0.4)]

    result = add_strategies_by_portfolio_id(session, 7, strategies)

    assert isinstance(result, StrategyConfig)
    assert result.portfolio_id == 7
    assert result.strategies == strategies
    session.add.assert_called_once_with(result)


def test_add_strategies_by_portfolio_id_supports_empty_strategy_list() -> None:
    """创建记录时应保留空策略列表。"""
    session = MagicMock()

    result = add_strategies_by_portfolio_id(session, 9, [])

    assert result.portfolio_id == 9
    assert result.strategies == []
    session.add.assert_called_once_with(result)


def test_get_portfolios_every_account_returns_latest_portfolio_mapping() -> None:
    """应返回每个账户最新的组合绑定记录，包括解绑记录。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            portfolio_old = _build_portfolio("old")
            portfolio_new = _build_portfolio("new")
            portfolio_other = _build_portfolio("other")
            account_a = _build_account("account-a")
            account_b = _build_account("account-b")

            session.add_all([portfolio_old, portfolio_new, portfolio_other, account_a, account_b])
            await session.commit()

            assert portfolio_old.id is not None
            assert portfolio_new.id is not None
            assert portfolio_other.id is not None
            assert account_a.id is not None
            assert account_b.id is not None

            session.add_all(
                [
                    PortfolioAccount(account_id=account_a.id, portfolio_id=portfolio_old.id),
                    PortfolioAccount(account_id=account_a.id, portfolio_id=portfolio_new.id),
                    PortfolioAccount(account_id=account_b.id, portfolio_id=portfolio_other.id),
                    PortfolioAccount(account_id=account_b.id, portfolio_id=None),
                ]
            )
            await session.commit()

            result = await get_portfolios_every_account(session)

            assert result == {
                account_a.id: portfolio_new.id,
                account_b.id: None,
            }

    asyncio.run(scenario())


def test_get_portfolio_strategies_and_account_returns_latest_records() -> None:
    """应使用某组合最新的策略配置和最新的账户绑定记录。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            portfolio = _build_portfolio("combo")
            account_old = _build_account("account-old")
            account_new = _build_account("account-new")
            session.add_all([portfolio, account_old, account_new])
            await session.commit()

            assert portfolio.id is not None
            assert account_old.id is not None
            assert account_new.id is not None

            session.add_all(
                [
                    StrategyConfig(portfolio_id=portfolio.id, strategies=[_strategy("legacy", 1.0)]),
                    StrategyConfig(
                        portfolio_id=portfolio.id,
                        strategies=[_strategy("alpha", 0.6), _strategy("beta", 0.4)],
                    ),
                    PortfolioAccount(account_id=account_old.id, portfolio_id=portfolio.id),
                    PortfolioAccount(account_id=account_new.id, portfolio_id=portfolio.id),
                ]
            )
            await session.commit()

            strategies, account_id = await get_portfolio_strategies_and_account(session, portfolio.id)

            assert strategies == [_strategy("alpha", 0.6), _strategy("beta", 0.4)]
            assert account_id == account_new.id

    asyncio.run(scenario())


def test_get_portfolio_strategies_and_account_returns_empty_list_without_strategy_config() -> None:
    """当组合没有持久化策略配置时，应返回空策略列表。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            portfolio = _build_portfolio("no-strategy")
            account = _build_account("bound-account")
            session.add_all([portfolio, account])
            await session.commit()

            assert portfolio.id is not None
            assert account.id is not None

            session.add(PortfolioAccount(account_id=account.id, portfolio_id=portfolio.id))
            await session.commit()

            strategies, account_id = await get_portfolio_strategies_and_account(session, portfolio.id)

            assert strategies == []
            assert account_id == account.id

    asyncio.run(scenario())


def test_get_recent_execute_records_orders_and_limits() -> None:
    """应按 id 倒序返回指定账户最近若干条记录，且不含其他账户。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account("acc")
            other = _build_account("other")
            session.add_all([account, other])
            await session.commit()

            assert account.id is not None
            assert other.id is not None

            for i in range(3):
                session.add(
                    ExecuteRecord(
                        account_id=account.id,
                        raw_input={},
                        raw_result={"account_assets": {"total_asset": float(i)}},
                        is_success=1,
                        strategy_config=[],
                    )
                )
            session.add(
                ExecuteRecord(
                    account_id=other.id,
                    raw_input={},
                    raw_result={},
                    is_success=0,
                    strategy_config=[],
                )
            )
            await session.commit()

            recent = await get_recent_execute_records_by_account_id(session, account.id, limit=2)

            assert len(recent) == 2
            # 最后插入(total_asset=2)的 id 最大，倒序应排最前。
            assert recent[0].raw_result["account_assets"]["total_asset"] == 2.0
            assert all(record.account_id == account.id for record in recent)

    asyncio.run(scenario())


def test_get_latest_strategies_by_account_id_returns_none_without_binding() -> None:
    """当账户当前没有组合绑定时，应返回 None。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            account = _build_account("unbound")
            session.add(account)
            await session.commit()

            assert account.id is not None

            result = await get_latest_strategies_by_account_id(session, account.id)

            assert result is None

    asyncio.run(scenario())


def test_get_latest_strategies_by_account_id_follows_latest_bound_portfolio() -> None:
    """应通过账户最新绑定的组合解析出最新策略。"""

    async def scenario() -> None:
        async with _session_scope() as session:
            portfolio_old = _build_portfolio("old-portfolio")
            portfolio_new = _build_portfolio("new-portfolio")
            account = _build_account("rotating-account")
            session.add_all([portfolio_old, portfolio_new, account])
            await session.commit()

            assert portfolio_old.id is not None
            assert portfolio_new.id is not None
            assert account.id is not None

            session.add_all(
                [
                    StrategyConfig(portfolio_id=portfolio_old.id, strategies=[_strategy("legacy", 1.0)]),
                    StrategyConfig(portfolio_id=portfolio_new.id, strategies=[_strategy("fresh", 1.0)]),
                    PortfolioAccount(account_id=account.id, portfolio_id=portfolio_old.id),
                    PortfolioAccount(account_id=account.id, portfolio_id=portfolio_new.id),
                ]
            )
            await session.commit()

            result = await get_latest_strategies_by_account_id(session, account.id)

            assert result is not None
            assert result.strategies == [_strategy("fresh", 1.0)]

    asyncio.run(scenario())

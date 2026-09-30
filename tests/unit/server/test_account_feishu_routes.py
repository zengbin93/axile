"""账户级飞书通知测试路由测试."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.server.api.routes import account_feishu
from axile.server.api.routes.account_feishu import AccountFeishuTestRequest
from tests.unit.server._execution_test_support import build_account


def test_notification_function_test_uses_sample_without_channel_query(monkeypatch) -> None:
    """通知函数试跑使用样例上下文，不连接交易渠道。"""
    account = build_account()
    captured = []

    async def _get_account(_session: object, _account_id: int):
        return account

    async def _unexpected_query(_account: object):
        raise AssertionError("函数试跑不应查询账户资产")

    async def _no_snapshot(_session: object, _account_id: int, _portfolio_id: int):
        return None

    monkeypatch.setattr(account_feishu, "_get_account_or_404", _get_account)
    monkeypatch.setattr(account_feishu, "query_account_assets", _unexpected_query)
    monkeypatch.setattr(account_feishu, "get_latest_account_target_snapshot", _no_snapshot)
    monkeypatch.setattr(
        account_feishu,
        "run_notification_function",
        lambda code, context, **kwargs: captured.append((code, context, kwargs)) or SimpleNamespace(ok=True),
    )
    result = asyncio.run(
        account_feishu.test_account_notification_function(
            SimpleNamespace(close=AsyncMock(), get=AsyncMock()),
            1,
            account_feishu.AccountNotificationFunctionTestRequest(
                code="def notify(context): pass", feishu_key="draft-key"
            ),
        )
    )
    assert result.ok is True
    assert captured[0][1]["execution"]["is_test"] is True
    assert captured[0][2]["feishu_key"] == "draft-key"


def _sample_assets() -> UnifiedAccountAssets:
    return UnifiedAccountAssets(
        available_cash=50000.0,
        total_asset=100000.0,
        market_value=50000.0,
        positions=[
            Position(
                symbol="rb2610",
                volume=10.0,
                available_volume=10.0,
                market_value=35000.0,
                direction=PositionDirection.LONG,
                avg_price=3500.0,
            ),
            Position(
                symbol="au2506",
                volume=2.0,
                available_volume=2.0,
                market_value=15000.0,
                direction=PositionDirection.LONG,
                avg_price=750.0,
            ),
        ],
    )


def test_default_card_test_push_carries_sample_trades(monkeypatch) -> None:
    """默认卡片测试应携带由真实持仓派生的样例成交，并带「样例」标记。"""
    account = build_account()
    pushed: list[tuple[dict[str, object], str]] = []

    async def _get_account(_session: object, _account_id: int):
        return account

    async def _query_assets(_account: object):
        return _sample_assets()

    async def _no_snapshot(_session: object, _account_id: int, _portfolio_id: int):
        return None

    monkeypatch.setattr(account_feishu, "_get_account_or_404", _get_account)
    monkeypatch.setattr(account_feishu, "query_account_assets", _query_assets)
    monkeypatch.setattr(account_feishu, "get_latest_account_target_snapshot", _no_snapshot)
    monkeypatch.setattr(account_feishu, "push_feishu_card", lambda card, key: pushed.append((card, key)))

    result = asyncio.run(
        account_feishu.test_account_feishu(
            SimpleNamespace(close=AsyncMock()), 1, AccountFeishuTestRequest(feishu_key="hook-test")
        )
    )

    assert result.ok is True
    card, key = pushed[0]
    assert key == "hook-test"
    data = card["data"]
    assert isinstance(data, dict)
    variables = data["template_variable"]
    assert isinstance(variables, dict)
    assert variables["account_mark"] == "ctp-sim（样例）"
    trades = variables["trades"]
    assert isinstance(trades, list)
    assert [(trade["symbol"], trade["operate"]) for trade in trades] == [
        ("rb2610", "买入"),
        ("au2506", "卖出"),
    ]
    positions = {position["symbol"]: position for position in variables["positions"]}
    # 首腿加仓一倍、次腿减半：目标量与真实执行同口径聚合自 symbol_results。
    assert positions["rb2610"]["target_volume"] == "20.0000"
    assert positions["au2506"]["target_volume"] == "1.0000"


def test_account_notification_test_runs_async_draft(monkeypatch, tmp_path) -> None:
    account = build_account()
    monkeypatch.setattr(account_feishu, "_get_account_or_404", AsyncMock(return_value=account))
    monkeypatch.setattr(account_feishu, "get_latest_account_target_snapshot", AsyncMock(return_value=None))
    output = tmp_path / "account-notification.txt"
    code = f"""import asyncio
import os
from pathlib import Path
async def notify(context):
    await asyncio.sleep(0)
    assert context['execution']['is_test'] is True
    assert context['execution']['kind'] == 'test'
    Path({str(output)!r}).write_text(os.environ['AXILE_ACCOUNT_FEISHU_KEY'])
"""
    result = asyncio.run(
        account_feishu.test_account_notification_function(
            SimpleNamespace(close=AsyncMock(), get=AsyncMock()),
            1,
            account_feishu.AccountNotificationFunctionTestRequest(code=code, feishu_key="draft-key"),
        )
    )
    assert result.ok is True
    assert output.read_text() == "draft-key"


def test_default_notification_without_key_points_to_basic_page(monkeypatch) -> None:
    """默认源码比较忽略首尾空白，缺少凭证时引导回基本信息页。"""
    account = build_account()
    account.feishu_key = None
    monkeypatch.setattr(account_feishu, "_get_account_or_404", AsyncMock(return_value=account))
    monkeypatch.setattr(account_feishu, "_build_sample_output", AsyncMock(return_value=object()))
    monkeypatch.setattr(account_feishu, "build_execution_notification_context", lambda *args, **kwargs: {})
    result = asyncio.run(
        account_feishu.test_account_notification_function(
            SimpleNamespace(),
            1,
            account_feishu.AccountNotificationFunctionTestRequest(
                code=f"\n{account_feishu.DEFAULT_ACCOUNT_NOTIFICATION_CODE}\n"
            ),
        )
    )
    assert result.ok is False
    assert result.message == "请返回基本信息页配置飞书 Webhook"
    assert account.execution_notification_code is None


def test_custom_notification_uses_saved_key_without_saving(monkeypatch) -> None:
    """通用函数无需飞书凭证；省略凭证字段时继续使用账户保存值。"""
    account = build_account()
    captured = []
    monkeypatch.setattr(account_feishu, "_get_account_or_404", AsyncMock(return_value=account))
    monkeypatch.setattr(account_feishu, "_build_sample_output", AsyncMock(return_value=object()))
    monkeypatch.setattr(account_feishu, "build_execution_notification_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        account_feishu,
        "run_notification_function",
        lambda code, context, **kwargs: captured.append(kwargs) or SimpleNamespace(ok=True),
    )
    for key in (None, "saved-key"):
        account.feishu_key = key
        result = asyncio.run(
            account_feishu.test_account_notification_function(
                SimpleNamespace(),
                1,
                account_feishu.AccountNotificationFunctionTestRequest(code="def notify(context): pass"),
            )
        )
        assert result.ok is True
        assert captured[-1]["feishu_key"] == key
        assert account.feishu_key == key
        assert account.execution_notification_code is None

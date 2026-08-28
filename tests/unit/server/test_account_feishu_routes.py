"""账户级飞书通知测试路由测试."""

import asyncio
from types import SimpleNamespace

from axile.executor.models.unified_account_assets import Position, PositionDirection, UnifiedAccountAssets
from axile.server.api.routes import account_feishu
from axile.server.api.routes.account_feishu import AccountFeishuTestRequest
from tests.unit.server._execution_test_support import build_account


def test_custom_card_test_push_skips_account_asset_query(monkeypatch) -> None:
    """原样自定义卡片测试不应建立交易渠道连接."""
    account = build_account()
    pushed: list[tuple[dict[str, object], str]] = []

    async def _get_account(_session: object, _account_id: int):
        return account

    async def _unexpected_query(_account: object):
        raise AssertionError("自定义卡片不应查询账户资产")

    monkeypatch.setattr(account_feishu, "_get_account_or_404", _get_account)
    monkeypatch.setattr(account_feishu, "query_account_assets", _unexpected_query)
    monkeypatch.setattr(account_feishu, "push_feishu_card", lambda card, key: pushed.append((card, key)))

    result = asyncio.run(
        account_feishu.test_account_feishu(
            object(),
            1,
            AccountFeishuTestRequest(
                feishu_key="hook-test",
                feishu_card_config={"mode": "custom", "card": {"header": {}, "elements": []}},
            ),
        )
    )

    assert result.ok is True
    assert pushed == [({"header": {}, "elements": []}, "hook-test")]


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
        account_feishu.test_account_feishu(object(), 1, AccountFeishuTestRequest(feishu_key="hook-test"))
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


def test_template_card_test_push_uses_target_snapshot_weights(monkeypatch) -> None:
    """模板卡片测试应以账户最近目标权重快照作为样例目标。"""
    account = build_account()
    pushed: list[tuple[dict[str, object], str]] = []

    async def _get_account(_session: object, _account_id: int):
        return account

    async def _query_assets(_account: object):
        return _sample_assets()

    async def _snapshot(_session: object, _account_id: int, _portfolio_id: int):
        return SimpleNamespace(normalized_weights={"rb2610": 0.6, "au2506": 0.4})

    monkeypatch.setattr(account_feishu, "_get_account_or_404", _get_account)
    monkeypatch.setattr(account_feishu, "query_account_assets", _query_assets)
    monkeypatch.setattr(account_feishu, "get_latest_account_target_snapshot", _snapshot)
    monkeypatch.setattr(account_feishu, "push_feishu_card", lambda card, key: pushed.append((card, key)))

    result = asyncio.run(
        account_feishu.test_account_feishu(
            object(),
            1,
            AccountFeishuTestRequest(
                feishu_key="hook-test",
                feishu_card_config={"mode": "template", "template_id": "tpl-demo"},
            ),
        )
    )

    assert result.ok is True
    card, _key = pushed[0]
    data = card["data"]
    assert isinstance(data, dict)
    assert data["template_id"] == "tpl-demo"
    variables = data["template_variable"]
    assert isinstance(variables, dict)
    assert variables["targets"]["current"] == {"rb2610": 0.6, "au2506": 0.4}
    assert variables["execution"]["is_test"] is True
    assert variables["execution"]["status"] == "SUCCEEDED"

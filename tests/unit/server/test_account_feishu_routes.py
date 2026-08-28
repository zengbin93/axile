"""账户级飞书通知测试路由测试."""

import asyncio

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

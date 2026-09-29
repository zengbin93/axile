"""账户默认飞书执行通知函数的可编辑源码。"""

DEFAULT_ACCOUNT_NOTIFICATION_CODE = '''import os

from axile.common.feishu import push_feishu_card
from axile.common.notification_context import AccountNotificationContext


def notify(context: AccountNotificationContext) -> None:
    """发送与内置默认通知一致的飞书卡片。"""
    key = os.environ.get("AXILE_ACCOUNT_FEISHU_KEY")
    if not key:
        return

    # 保留原默认卡片的口径；可以在这里修改字段、持仓或成交的展示。
    defaults = context["default_feishu_variables"]
    variables = {
        "account_mark": defaults["account_mark"],
        "dt": defaults["dt"],
        "algorithm": defaults["algorithm"],
        "total_assets": defaults["total_assets"],
        "available_cash": defaults["available_cash"],
        "market_value": defaults["market_value"],
        "positions": defaults["positions"],
        "trades": defaults["trades"],
    }
    card = {
        "type": "template",
        "data": {
            "template_id": "AAqRUQhyOM90g",
            "template_variable": variables,
        },
    }
    push_feishu_card(card, key, timeout=10)
'''

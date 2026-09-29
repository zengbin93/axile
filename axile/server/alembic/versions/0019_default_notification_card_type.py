"""Correct the stored default Feishu function's card type annotation."""

import sqlalchemy as sa
from alembic import op

from axile.common.default_account_notification import DEFAULT_ACCOUNT_NOTIFICATION_CODE

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_OLD_DEFAULT_CODE = '''import os

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


def upgrade() -> None:
    """仅更新与旧默认源码完全一致的账户，保留用户改写的函数。"""
    op.get_bind().execute(
        sa.text("UPDATE account SET execution_notification_code = :new WHERE execution_notification_code = :old"),
        {"new": DEFAULT_ACCOUNT_NOTIFICATION_CODE, "old": _OLD_DEFAULT_CODE},
    )


def downgrade() -> None:
    """源码类型修正可在旧 schema 中运行，不回退账户已保存的源码。"""

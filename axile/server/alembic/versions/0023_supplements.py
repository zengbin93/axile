"""独立补发计划与持久化通知事件。"""

import json

import sqlalchemy as sa
from alembic import op

OLD_DEFAULT = 'import os\n\nfrom axile.common.feishu import push_feishu_card\nfrom axile.common.notification_context import AccountNotificationContext\n\n\ndef notify(context: AccountNotificationContext) -> None:\n    """发送与内置默认通知一致的飞书卡片。"""\n    key = os.environ.get("AXILE_ACCOUNT_FEISHU_KEY")\n    if not key:\n        return\n\n    # 保留原默认卡片的口径；可以在这里修改字段、持仓或成交的展示。\n    defaults = context["default_feishu_variables"]\n    variables = {\n        "account_mark": defaults["account_mark"],\n        "dt": defaults["dt"],\n        "algorithm": defaults["algorithm"],\n        "total_assets": defaults["total_assets"],\n        "available_cash": defaults["available_cash"],\n        "market_value": defaults["market_value"],\n        "positions": defaults["positions"],\n        "trades": defaults["trades"],\n    }\n    card: dict[str, object] = {\n        "type": "template",\n        "data": {\n            "template_id": "AAqRUQhyOM90g",\n            "template_variable": variables,\n        },\n    }\n    push_feishu_card(card, key, timeout=10)\n'
NEW_DEFAULT = 'import os\n\nfrom axile.common.feishu import push_feishu_card\nfrom axile.common.notification_context import AccountNotificationContext\n\n\ndef notify(context: AccountNotificationContext) -> None:\n    """发送与内置默认通知一致的飞书卡片。"""\n    key = os.environ.get("AXILE_ACCOUNT_FEISHU_KEY")\n    if not key:\n        return\n\n    if context.get("event_type") == "supplement.cancelled":\n        group = context["supplement"]\n        card = {\n            "header": {"title": {"tag": "plain_text", "content": "剩余补发已取消"}},\n            "elements": [{"tag": "markdown", "content": f"账户：{context[\'account\'].get(\'name\', \'\')}\\n原因：{group[\'reason\']}\\n请求时间：{group[\'cancel_requested_at\']}"}],\n        }\n        push_feishu_card(card, key, timeout=10)\n        return\n\n    # 保留原默认卡片的口径；可以在这里修改字段、持仓或成交的展示。\n    defaults = context["default_feishu_variables"]\n    variables = {\n        "account_mark": defaults["account_mark"],\n        "dt": defaults["dt"],\n        "algorithm": defaults["algorithm"],\n        "total_assets": defaults["total_assets"],\n        "available_cash": defaults["available_cash"],\n        "market_value": defaults["market_value"],\n        "positions": defaults["positions"],\n        "trades": defaults["trades"],\n    }\n    card: dict[str, object] = {\n        "type": "template",\n        "data": {\n            "template_id": "AAqRUQhyOM90g",\n            "template_variable": variables,\n        },\n    }\n    push_feishu_card(card, key, timeout=10)\n'

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """旧 schedule JSON 无需回填，缺省 supplement 保持为空。"""
    connection = op.get_bind()
    for row in connection.execute(sa.text("SELECT account_id, notification FROM account_settings")).mappings():
        value = json.loads(row["notification"]) if isinstance(row["notification"], str) else dict(row["notification"])
        if value.get("execution_notification_code") == OLD_DEFAULT:
            value["execution_notification_code"] = NEW_DEFAULT
            connection.execute(
                sa.text("UPDATE account_settings SET notification = :value WHERE account_id = :id"),
                {"value": json.dumps(value, ensure_ascii=False), "id": row["account_id"]},
            )
    op.add_column("account_notification_state", sa.Column("last_attempt_event_type", sa.String(), nullable=True))
    op.create_table(
        "supplement_group",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("base_scheduled_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("configured_count", sa.Integer(), nullable=False),
        sa.Column("effective_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("end_reason", sa.String(), nullable=True),
        sa.Column("cancel_requested_at", sa.String(), nullable=True),
        sa.UniqueConstraint("account_id", "fingerprint", "base_scheduled_at"),
    )
    op.create_table(
        "supplement_step",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_id", sa.Text(), sa.ForeignKey("supplement_group.id", ondelete="CASCADE"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.UniqueConstraint("group_id", "index"),
    )
    op.create_index("ix_supplement_step_execution_id", "supplement_step", ["execution_id"])
    op.create_table(
        "notification_event",
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("id", sa.Text(), nullable=False, unique=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """删除补发运行态，不更改旧账户 cron。"""
    for table in ("notification_event", "supplement_step", "supplement_group"):
        op.drop_table(table)
    op.drop_column("account_notification_state", "last_attempt_event_type")
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE account_settings SET schedule = json_remove(schedule, '$.supplement')"))
    for row in connection.execute(sa.text("SELECT account_id, notification FROM account_settings")).mappings():
        value = json.loads(row["notification"]) if isinstance(row["notification"], str) else dict(row["notification"])
        if value.get("execution_notification_code") == NEW_DEFAULT:
            value["execution_notification_code"] = OLD_DEFAULT
            connection.execute(
                sa.text("UPDATE account_settings SET notification = :value WHERE account_id = :id"),
                {"value": json.dumps(value, ensure_ascii=False), "id": row["account_id"]},
            )

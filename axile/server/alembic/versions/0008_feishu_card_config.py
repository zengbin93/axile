"""新增账户飞书通知卡片配置.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为历史账户增加可空的飞书卡片配置字段."""
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("account")}
    if "feishu_card_config" not in columns:
        op.add_column("account", sa.Column("feishu_card_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    """删除飞书卡片配置字段."""
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("account")}
    if "feishu_card_config" in columns:
        op.drop_column("account", "feishu_card_config")

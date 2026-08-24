"""将 Binance 测试网标记迁移为连接网络。

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_account = sa.table(
    "account",
    sa.column("id", sa.Integer()),
    sa.column("trade_channel", sa.Text()),
    sa.column("account_config", sa.JSON()),
)


def _rewrite_config(*, upgrade: bool) -> None:
    """逐行改写 Binance 账户 JSON，保持数据库方言无关。"""
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(_account.c.id, _account.c.account_config).where(_account.c.trade_channel == "binance")
    )
    for account_id, raw_config in rows:
        if not isinstance(raw_config, dict):
            continue
        config = dict(raw_config)
        if upgrade:
            if "is_testnet" not in config:
                continue
            is_testnet = config.pop("is_testnet")
            config.setdefault("network", "testnet" if is_testnet is True else "mainnet")
        else:
            if "network" not in config:
                continue
            network = config.pop("network")
            config.setdefault("is_testnet", network == "testnet")
        connection.execute(sa.update(_account).where(_account.c.id == account_id).values(account_config=config))


def upgrade() -> None:
    """把 ``is_testnet`` 转换为 ``network``。"""
    _rewrite_config(upgrade=True)


def downgrade() -> None:
    """把 ``network`` 还原为 ``is_testnet``。"""
    _rewrite_config(upgrade=False)

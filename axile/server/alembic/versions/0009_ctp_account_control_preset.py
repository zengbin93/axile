"""将仍使用通用 preset 的存量 CTP 账户迁移到 CTP preset.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只迁移 CTP 渠道仍显式绑定 default 的账户。"""
    op.execute(
        "UPDATE account SET account_control_preset = 'ctp' "
        "WHERE trade_channel = 'ctp' AND account_control_preset = 'default'"
    )


def downgrade() -> None:
    """不猜测迁移后用户对 preset 的显式选择。"""

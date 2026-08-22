"""为策略配置增加仓位类型。

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


def upgrade() -> None:
    """增加仓位类型，并将现有数据源型配置迁移为时序类型。"""
    op.add_column("strategyconfig", sa.Column("weight_type", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE strategyconfig
        SET weight_type = 'ts'
        WHERE portfolio_id IN (
            SELECT id FROM portfolio
            WHERE custom_calc_py_code IS NULL OR trim(custom_calc_py_code) = ''
        )
        """
    )


def downgrade() -> None:
    """删除策略配置的仓位类型。"""
    op.drop_column("strategyconfig", "weight_type")

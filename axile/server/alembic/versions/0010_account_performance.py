"""持久化账户回测模式和单边费率."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为现有账户初始化时序、零费率."""
    op.add_column("account", sa.Column("backtest_weight_type", sa.Text(), nullable=False, server_default="ts"))
    op.add_column("account", sa.Column("backtest_fee_rate", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    """移除绩效设置，不影响执行记录."""
    with op.batch_alter_table("account") as batch:
        batch.drop_column("backtest_fee_rate")
        batch.drop_column("backtest_weight_type")

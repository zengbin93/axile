"""Replace account Feishu card overrides with one notification function."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop obsolete card data and add the account function fields."""
    op.add_column(
        "account", sa.Column("execution_notification_mode", sa.Text(), nullable=False, server_default="default")
    )
    op.add_column("account", sa.Column("execution_notification_code", sa.Text(), nullable=True))
    op.drop_column("account", "feishu_card_config")


def downgrade() -> None:
    """Restore the old nullable card column without its discarded values."""
    op.add_column("account", sa.Column("feishu_card_config", sa.JSON(), nullable=True))
    op.drop_column("account", "execution_notification_code")
    op.drop_column("account", "execution_notification_mode")

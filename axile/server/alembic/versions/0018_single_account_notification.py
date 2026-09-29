"""Represent each account notification with zero or one function."""

import sqlalchemy as sa
from alembic import op

from axile.common.default_account_notification import DEFAULT_ACCOUNT_NOTIFICATION_CODE

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Convert enabled built-in Feishu notifications to the editable function."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE account SET execution_notification_code = :code "
            "WHERE execution_notification_mode = 'default' AND feishu_key IS NOT NULL AND feishu_key != ''"
        ),
        {"code": DEFAULT_ACCOUNT_NOTIFICATION_CODE},
    )
    connection.execute(
        sa.text(
            "UPDATE account SET execution_notification_code = NULL "
            "WHERE execution_notification_mode = 'default' AND (feishu_key IS NULL OR feishu_key = '')"
        )
    )
    op.drop_column("account", "execution_notification_mode")


def downgrade() -> None:
    """Restore the old mode column using function presence."""
    op.add_column(
        "account", sa.Column("execution_notification_mode", sa.Text(), nullable=False, server_default="default")
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE account SET execution_notification_mode = 'function' "
            "WHERE execution_notification_code IS NOT NULL AND execution_notification_code != :code"
        ),
        {"code": DEFAULT_ACCOUNT_NOTIFICATION_CODE},
    )
    connection.execute(
        sa.text("UPDATE account SET execution_notification_code = NULL WHERE execution_notification_code = :code"),
        {"code": DEFAULT_ACCOUNT_NOTIFICATION_CODE},
    )

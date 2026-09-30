"""Persist the latest account notification result, including failures."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加最近结果字段，允许首次通知失败时尚无成功时间。"""
    op.execute("DROP TRIGGER IF EXISTS account_settings_delete")
    with op.batch_alter_table("account_notification_state") as batch:
        batch.alter_column("last_success_at", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("last_attempt_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_attempt_execution_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_attempt_ok", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("last_attempt_error", sa.Text(), nullable=True))

    _restore_delete_trigger()


def downgrade() -> None:
    """恢复仅保存成功摘要的结构。"""
    op.execute("DELETE FROM account_notification_state WHERE last_success_at IS NULL")
    op.execute("DROP TRIGGER IF EXISTS account_settings_delete")
    with op.batch_alter_table("account_notification_state") as batch:
        for name in ("last_attempt_error", "last_attempt_ok", "last_attempt_execution_id", "last_attempt_at"):
            batch.drop_column(name)
        batch.alter_column("last_success_at", existing_type=sa.Text(), nullable=False)

    _restore_delete_trigger()


def _restore_delete_trigger() -> None:
    """SQLite 重建表后恢复账户级联删除触发器。"""
    op.execute("""CREATE TRIGGER account_settings_delete AFTER DELETE ON account
        BEGIN
        DELETE FROM account_settings WHERE account_id = OLD.id;
        DELETE FROM account_notification_state WHERE account_id = OLD.id;
        END""")

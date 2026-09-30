"""后台通知线程使用独立同步连接保存成功摘要。"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, literal, select
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import col

from axile.common.config import settings
from axile.server.db.models.account_notification import AccountNotificationState


@lru_cache(maxsize=1)
def _notification_engine() -> Engine:
    """线程与 worker 各自创建连接池，不复用 asyncio session。"""
    engine = create_engine(str(settings.sqlalchemy_database_uri).replace("sqlite+aiosqlite:", "sqlite:"))

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def record_notification_success(account_id: int, execution_id: str | None, succeeded_at: str) -> None:
    """只覆盖为更晚的成功；账户已删除时跳过。"""
    from axile.server.db.models import Account

    statement = insert(AccountNotificationState).from_select(
        ["account_id", "last_success_at", "execution_id"],
        select(col(Account.id), literal(succeeded_at), literal(execution_id)).where(col(Account.id) == account_id),
    )
    statement = statement.on_conflict_do_update(
        index_elements=["account_id"],
        set_={"last_success_at": succeeded_at, "execution_id": execution_id},
        where=col(AccountNotificationState.last_success_at) < succeeded_at,
    )
    with _notification_engine().begin() as connection:
        connection.execute(statement)

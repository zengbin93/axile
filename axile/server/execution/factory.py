"""按运行时注册的交易渠道创建执行器实例."""

from axile.channels import get_channel
from axile.common.config import settings
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.trading_calendar import SqliteTradingCalendar
from axile.server.db.models import Account


def create_executor_instance(account: Account) -> AbstractExecutor:
    """
    根据交易渠道创建相应的执行器实例.

    Parameters
    ----------
    account : Account
        待执行的账户模型。

    Returns
    -------
    AbstractExecutor
        与账户交易渠道匹配的执行器实例。

    Raises
    ------
    ValueError
        当交易渠道未被支持时抛出。
    """
    try:
        plugin = get_channel(account.trade_channel)
    except KeyError as exc:
        raise ValueError(f"未注册交易渠道: {account.trade_channel}") from exc
    config_data = dict(account.account_config)
    config_data["channel_type"] = account.trade_channel
    config = plugin.account_config_model.model_validate(config_data)
    executor = plugin.create_executor(config)
    set_trading_calendar = getattr(executor, "set_trading_calendar", None)
    if callable(set_trading_calendar):
        _ = set_trading_calendar(SqliteTradingCalendar.from_database_uri(str(settings.sqlalchemy_database_uri)))
    set_channel_calendar = getattr(executor, "set_channel_calendar", None)
    if callable(set_channel_calendar):
        calendar = plugin.descriptor.calendar
        _ = set_channel_calendar(
            calendar.calendar_id if calendar is not None else None,
            calendar.fallback_calendar_id if calendar is not None else None,
        )
    return executor

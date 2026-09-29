"""自定义通知函数接收的公开数据结构。"""

from typing import TypedDict


class AccountNotificationExecution(TypedDict):
    """账户执行通知中的执行摘要。"""

    id: str | None
    status: str
    success: bool
    outcome: str | None
    reason_code: str | None
    error: str | None
    is_test: bool


class AccountNotificationSummary(TypedDict):
    """账户执行通知中的计数摘要。"""

    symbol_count: int
    position_count: int | None
    order_count: int
    filled_order_count: int
    active_order_count: int
    trade_count: int
    trade_value: float
    succeeded_symbol_count: int
    failed_symbol_count: int


class AccountNotificationContext(TypedDict):
    """账户执行结束时交给 ``notify`` 的脱敏快照。"""

    event_id: str | None
    account: dict[str, object]
    execution: AccountNotificationExecution
    strategy: dict[str, object]
    assets: dict[str, object]
    targets: dict[str, object]
    positions: list[dict[str, object]] | None
    orders: list[dict[str, object]]
    trades: list[dict[str, object]]
    symbols: list[dict[str, object]]
    summary: AccountNotificationSummary
    default_feishu_variables: dict[str, object]


class SystemNotificationError(TypedDict):
    """系统级执行错误内容。"""

    type: str
    message: str
    traceback: str


class SystemNotificationAccount(TypedDict):
    """系统级通知中的账户标识。"""

    id: int | None
    name: str


class SystemNotificationContext(TypedDict):
    """系统执行错误交给 ``notify`` 的上下文。"""

    event_id: str
    event_type: str
    execution_id: str | None
    occurred_at: str
    account: SystemNotificationAccount | None
    error: SystemNotificationError
    is_test: bool

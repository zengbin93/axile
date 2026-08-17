"""定义账户控制流程使用的异常类型."""

from __future__ import annotations

from axile.common.trade_channel import TradeChannel


class AccountControlBlockedError(RuntimeError):
    """
    表示账户控制拒绝本次对外交互的异常.

    Attributes
    ----------
    account_id : int | None
        被拒绝的账户 ID。
    execution_id : str | None
        当前执行会话 ID。
    channel : TradeChannel
        触发拒绝的交易渠道。
    operation : str
        被拒绝的操作键。
    symbol : str | None
        与本次调用关联的交易标的代码。
    """

    def __init__(
        self,
        message: str,
        *,
        account_id: int | None,
        execution_id: str | None,
        channel: TradeChannel,
        operation: str,
        symbol: str | None = None,
    ) -> None:
        super().__init__(message)
        self.account_id = account_id
        self.execution_id = execution_id
        self.channel = channel
        self.operation = operation
        self.symbol = symbol

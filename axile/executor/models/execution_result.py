"""
执行结果模型.

定义统一执行状态、单个品种的算法结果，以及成功态判断辅助函数。
"""

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData


class ExecutionStatus(StrEnum):
    """
    统一执行状态枚举.

    Attributes
    ----------
    SUCCEEDED : str
        执行成功并完成预期动作。
    NOOP : str
        无需执行任何动作。
    BLOCKED : str
        因前置条件不满足而阻塞。
    PARTIAL : str
        仅完成部分预期动作。
    FAILED : str
        执行失败。
    """

    SUCCEEDED = "SUCCEEDED"
    NOOP = "NOOP"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


def is_success_status(status: ExecutionStatus) -> bool:
    """
    判断执行状态是否属于成功态.

    Parameters
    ----------
    status : ExecutionStatus
        待判断的执行状态。

    Returns
    -------
    bool
        当状态属于成功集合时返回 ``True``。
    """
    return status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.NOOP}


class AlgorithmResult(BaseModel):
    """
    单个品种的算法执行结果.

    Attributes
    ----------
    symbol : str
        结果对应的品种代码。
    algorithm : str
        实际执行的算法名称。
    orders : list[UnifiedOrder]
        该品种产生的订单列表。
    trades : list[TradeRecord]
        该品种产生的成交明细列表。
    status : ExecutionStatus
        该品种的执行状态。
    error : str | None
        执行失败时的错误信息。
    """

    symbol: str = Field(default="", description="品种代码")
    algorithm: str = Field(default="", description="实际执行的算法名")
    orders: list[UnifiedOrder] = Field(default_factory=list, description="该品种产生的订单")
    trades: list[TradeRecord] = Field(default_factory=list, description="该品种产生的成交明细")
    target_volume: int | float | None = Field(default=None, description="该品种目标持仓数量")
    first_tick: UnifiedPriceData | None = Field(default=None, description="该品种首笔行情快照")
    memory: dict[str, object] = Field(default_factory=dict, description="算法附加信息")
    status: ExecutionStatus = Field(default=ExecutionStatus.SUCCEEDED, description="该品种执行状态")
    error: str | None = Field(default=None, description="该品种失败原因")
    account_assets: UnifiedAccountAssets | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="执行结束时的账户资产快照，仅供运行时使用",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        """
        返回当前结果是否属于成功态.

        Returns
        -------
        bool
            当 ``status`` 属于成功集合时返回 ``True``。
        """
        return is_success_status(self.status)

    def with_runtime_account_assets(self, account_assets: UnifiedAccountAssets | None) -> "AlgorithmResult":
        """
        为结果附加运行时账户资产快照.

        Parameters
        ----------
        account_assets : UnifiedAccountAssets | None
            执行结束时采集到的账户资产快照。

        Returns
        -------
        AlgorithmResult
            写入运行时账户资产后的当前结果对象。
        """
        self.account_assets = account_assets
        return self

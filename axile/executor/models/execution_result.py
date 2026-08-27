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


class TargetSizingStatus(StrEnum):
    """目标数量换算状态."""

    SIZED = "SIZED"
    UNAVAILABLE = "UNAVAILABLE"


class TargetSizingDecision(BaseModel):
    """单品种从账户目标到可执行数量的结构化换算证据."""

    symbol: str = Field(default="", description="品种代码")
    sizing_mode: str = Field(default="weight", description="目标输入口径")
    status: TargetSizingStatus = Field(default=TargetSizingStatus.SIZED, description="换算状态")
    reason_code: str = Field(default="COMMON.SIZING.EXACT", description="结构化换算原因")
    account_weight: float = Field(default=0.0, description="账户口径目标权重或直接数量")
    equity: float = Field(default=0.0, description="换算时账户权益")
    reference_price: float | None = Field(default=None, description="换算使用的参考价格")
    unit_multiplier: float | None = Field(default=None, description="价格到单位名义价值的乘数")
    unit_notional: float | None = Field(default=None, description="每个交易单位的名义价值")
    target_notional: float | None = Field(default=None, description="账户权重对应的目标名义价值")
    raw_quantity: float | None = Field(default=None, description="应用数量规则前的目标数量")
    target_quantity: float | None = Field(default=None, description="应用数量规则后的目标数量")
    current_quantity: float | None = Field(default=None, description="规划时当前带号持仓数量")
    quantity_step: float | None = Field(default=None, description="数量步长或整手单位")
    min_quantity: float | None = Field(default=None, description="最小可交易数量")
    min_notional: float | None = Field(default=None, description="最小可交易名义价值")


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
    sizing: TargetSizingDecision | None = Field(default=None, description="目标数量换算证据")
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

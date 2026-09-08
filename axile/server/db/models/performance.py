"""账户绩效设置与收益对比响应."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

WeightType = Literal["ts", "cs"]
FeeRate = Annotated[float, Field(strict=True, ge=0, lt=1, allow_inf_nan=False)]
RangeKey = Literal["30", "90", "all"]


class PerformanceSettings(BaseModel):
    """账户级回测设置，费率使用小数表示."""

    model_config = ConfigDict(extra="forbid")
    backtest_weight_type: WeightType
    backtest_fee_rate: FeeRate

    @field_validator("backtest_weight_type")
    @classmethod
    def account_weight_mode(cls, value: WeightType) -> WeightType:
        """旧 ts 配置兼容读入；账户资金权重必须求和，不能再次平均."""
        return "cs"


class PerformancePoint(BaseModel):
    """日收益及共享基准下的累计收益."""

    date: str
    observed_at: str
    record_id: int | None = None
    execution_id: str | None = None
    account_return: float | None = None
    account_equity: float | None = None
    portfolio_return: float | None = None
    account_daily_return: float | None = None
    portfolio_daily_return: float | None = None
    difference: float | None = None


class PerformanceGap(BaseModel):
    """首个无法继续累计的执行快照."""

    time: str
    execution_id: str | None
    reason: str
    symbols: list[str] = Field(default_factory=list)


class PerformanceBinding(BaseModel):
    """区间内组合绑定变更."""

    time: str
    portfolio_id: int | None


class AccountPerformance(BaseModel):
    """账户收益与组合回测的只读结果."""

    settings: PerformanceSettings
    backtest_included: bool = True
    engine_version: str
    range: RangeKey
    baseline: str | None = None
    end: str | None = None
    record_count: int = 0
    observation_count: int = 0
    used_record_count: int = 0
    invalid_asset_count: int = 0
    gap: PerformanceGap | None = None
    points: list[PerformancePoint] = Field(default_factory=list)
    bindings: list[PerformanceBinding] = Field(default_factory=list)
    executions: list[dict] = Field(default_factory=list)


class CostSummary(BaseModel):
    """成交额覆盖率、滑点及分币种手续费；未知金额保持空值."""

    value: float | None
    cost: float | None
    lossBp: float | None
    coverage: float | None
    covered: int
    count: int
    amountComplete: bool
    fees: dict[str, float]
    feeCovered: int


class PerformanceEvent(BaseModel):
    """有界账户时间线摘要."""

    time: str
    tag: str
    text: str
    executionId: str | None


class PerformanceSnapshot(BaseModel):
    """结果版本与源版本分离，失败或待更新时可同时携带上次成功结果."""

    status: Literal["empty", "pending", "ready", "stale", "failed"]
    source_version: int
    snapshot_id: str | None
    snapshot_version: int | None
    logic_version: str
    engine_version: str
    computed_at: str | None
    data_until: str | None
    settings: PerformanceSettings | None
    error: str | None
    retry_at: float | None
    result: AccountPerformance | None
    daily_costs: dict[str, CostSummary]
    events: list[PerformanceEvent]
    event_count: int


class PerformanceSummary(BaseModel):
    """卡片使用的全区间绩效投影，金额与曲线同版发布。"""

    snapshot_id: str | None = None
    status: Literal["empty", "pending", "ready", "stale", "failed"] = "empty"
    computed_at: str | None = None
    observed_at: str | None = None
    account_equity: float | None = None
    account_daily_return: float | None = None
    points: list[PerformancePoint] = Field(default_factory=list)

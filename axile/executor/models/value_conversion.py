"""保留规划时价格币种到审计金额币种的换算依据。"""

from pydantic import BaseModel, ConfigDict, Field


class PriceValueConversion(BaseModel):
    """一单位原生价格对应的账户计价金额；不改变报单与成交价格。"""

    model_config = ConfigDict(frozen=True)

    price_currency: str = Field(min_length=1, description="交易所原生价格币种")
    value_currency: str = Field(min_length=1, description="审计金额币种")
    rate: float = Field(gt=0, allow_inf_nan=False, description="原生价格到审计金额的汇率")
    reference: dict[str, object] = Field(default_factory=dict, description="规划时冻结的参考汇率证据")

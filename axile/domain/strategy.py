"""组合策略共享领域类型定义."""

from typing import Literal

from typing_extensions import NotRequired, TypedDict

WeightType = Literal["ts", "cs"]


class Strategy(TypedDict):
    """单个策略的标准结构."""

    name: str
    weight: float
    base_freq: NotRequired[str]
    description: NotRequired[str]
    outsample_sdt: NotRequired[str]

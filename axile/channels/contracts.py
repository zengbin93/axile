"""定义交易渠道插件的公开契约与描述模型."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from axile.executor.models.unified_input_accounts import BaseAccountConfig

if TYPE_CHECKING:
    from axile.executor.abstract_executor.base import AbstractExecutor

type ChannelId = str
type ExecutionBackend = Literal["thread", "process"]
type ExecutorFactory = Callable[[BaseAccountConfig], "AbstractExecutor"]
type TargetTransform = Callable[[dict[str, float], pd.DataFrame], pd.DataFrame]


class _FrozenDescriptorModel(BaseModel):
    """为渠道描述模型提供不可变且禁止额外字段的共同配置."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AlgorithmReference(_FrozenDescriptorModel):
    """
    描述渠道默认使用的算法及其参数.

    Attributes
    ----------
    method : str
        算法注册名称。
    params : dict[str, object]
        算法默认参数。
    """

    method: str = Field(min_length=1)
    params: dict[str, object] = Field(default_factory=dict)


class ChannelDefaults(_FrozenDescriptorModel):
    """
    描述新建账户时采用的渠道默认值.

    Attributes
    ----------
    long_leverage : float
        默认多头杠杆。
    short_leverage : float
        默认空头杠杆。
    execution_timeout : int
        默认执行总超时秒数。
    trade_algorithm : AlgorithmReference
        默认调仓算法。
    empty_positions_algorithm : AlgorithmReference | None
        默认清仓算法；为空时沿用执行器默认行为。
    """

    long_leverage: float = Field(ge=0)
    short_leverage: float = Field(ge=0)
    execution_timeout: int = Field(ge=1)
    trade_algorithm: AlgorithmReference
    empty_positions_algorithm: AlgorithmReference | None = None


class ChannelLeverage(_FrozenDescriptorModel):
    """
    描述渠道可配置的杠杆范围.

    Attributes
    ----------
    min : float
        最小值。
    max : float
        最大值。
    step : float
        最小调整步长。
    """

    min: float = Field(ge=0)
    max: float = Field(gt=0)
    step: float = Field(gt=0)


class ChannelUnits(_FrozenDescriptorModel):
    """
    描述渠道在界面中使用的数量与价格单位.

    Attributes
    ----------
    quantity_kind : Literal["share", "contract", "base_asset", "custom"]
        数量的业务语义；``base_asset`` 表示单位随品种变化。
    quantity_label : str
        数量后展示的短标签，例如“股”“手”或“基础资产”。
    quantity_max_decimals : int
        前端展示数量时允许保留的最大小数位数。
    price_label : str
        价格后展示的短标签；为空时使用渠道计价币种。
    notional_label : str
        成交金额后展示的短标签；为空时使用渠道计价币种。
    """

    quantity_kind: Literal["share", "contract", "base_asset", "custom"] = "custom"
    quantity_label: str = ""
    quantity_max_decimals: int = Field(default=6, ge=0, le=12)
    price_label: str = ""
    notional_label: str = ""


class ChannelUi(_FrozenDescriptorModel):
    """
    描述公共前端可消费的渠道界面差异.

    Attributes
    ----------
    account_connect_lead : str
        账户连接页的渠道专属说明；为空时使用公共说明。
    leverage_title : str
        杠杆配置区标题。
    leverage_note : str
        杠杆配置区的补充说明。
    long_leverage_label : str
        多头杠杆输入项标签。
    short_leverage_label : str
        空头杠杆输入项标签。
    show_short_leverage : bool
        是否展示并提交空头杠杆配置。
    """

    account_connect_lead: str = ""
    leverage_title: str = "杠杆"
    leverage_note: str = "多空可分设"
    long_leverage_label: str = "做多杠杆"
    short_leverage_label: str = "做空杠杆"
    show_short_leverage: bool = True


class ChannelAccountOption(_FrozenDescriptorModel):
    """描述账户表单选择字段中的一个选项."""

    value: str
    label: str


class ChannelAccountField(_FrozenDescriptorModel):
    """
    描述渠道账户表单中的一个字段.

    Attributes
    ----------
    name : str
        提交到账户配置中的字段名。
    label : str
        面向用户的字段标签。
    input : Literal["text", "password", "number", "boolean", "select"]
        前端输入控件类型。
    required : bool
        是否要求用户填写。
    help : str | None
        输入项下方展示的渠道专属说明。
    """

    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    input: Literal["text", "password", "number", "boolean", "select"] = "text"
    required: bool = True
    placeholder: str | None = None
    help: str | None = None
    default: object | None = None
    options: tuple[ChannelAccountOption, ...] = ()


class ChannelAccountNotice(_FrozenDescriptorModel):
    """描述账户连接表单旁展示的一条提示."""

    tone: Literal["info", "warning"] = "info"
    text: str = Field(min_length=1)


class ChannelAccountForm(_FrozenDescriptorModel):
    """描述渠道账户连接表单与提示信息."""

    fields: tuple[ChannelAccountField, ...] = ()
    notices: tuple[ChannelAccountNotice, ...] = ()


class ChannelDescriptor(_FrozenDescriptorModel):
    """
    描述前端与 API 可见的渠道静态能力.

    Attributes
    ----------
    channel : str
        全局唯一的渠道标识。
    label : str
        面向用户的渠道名称。
    description : str
        渠道用途简述。
    icon : str
        前端图标目录中的图标标识。
    market : str
        渠道所属市场类别。
    currency : str
        账户权益默认计价币种。
    units : ChannelUnits
        数量、价格与成交金额的展示单位。
    ui : ChannelUi
        公共前端可消费的渠道界面差异。
    defaults : ChannelDefaults
        新建账户默认值。
    leverage : ChannelLeverage
        可配置杠杆范围。
    account_form : ChannelAccountForm
        账户连接表单定义。
    """

    channel: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    icon: str = Field(min_length=1)
    market: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    units: ChannelUnits = Field(default_factory=ChannelUnits)
    ui: ChannelUi = Field(default_factory=ChannelUi)
    defaults: ChannelDefaults
    leverage: ChannelLeverage
    account_form: ChannelAccountForm


@dataclass(frozen=True, slots=True)
class ChannelPlugin:
    """
    聚合一个交易渠道的静态描述与运行时能力.

    Attributes
    ----------
    descriptor : ChannelDescriptor
        API 与前端可见的静态描述。
    account_config_model : type[BaseAccountConfig]
        用于验证渠道账户配置的 Pydantic 模型。
    create_executor : ExecutorFactory
        根据已验证配置创建执行器的工厂。
    target_transform : TargetTransform
        将策略权重表转换为渠道目标贡献度的函数。
    execution_backend : ExecutionBackend
        执行阻塞渠道逻辑所用的隔离后端。
    required_modules : tuple[str, ...]
        判断运行时可用性所需的顶层 Python 模块。
    install_extra : str | None
        公开包中对应的可选依赖 extra；外部插件通常为空。
    max_parallel_symbols : int
        单次执行允许并行处理的最大品种数。
    """

    descriptor: ChannelDescriptor
    account_config_model: type[BaseAccountConfig]
    create_executor: ExecutorFactory
    target_transform: TargetTransform
    execution_backend: ExecutionBackend = "thread"
    required_modules: tuple[str, ...] = ()
    install_extra: str | None = None
    max_parallel_symbols: int = 1

    def __post_init__(self) -> None:
        """校验插件运行时契约中的基本不变量."""
        if not issubclass(self.account_config_model, BaseAccountConfig):
            raise TypeError("account_config_model 必须继承 BaseAccountConfig")
        if self.max_parallel_symbols < 1:
            raise ValueError("max_parallel_symbols 必须大于等于 1")

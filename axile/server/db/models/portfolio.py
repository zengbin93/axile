"""组合与策略配置数据库模型."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Column, Connection, ForeignKey, Integer, Text, event
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import Mapper, relationship
from sqlmodel import Field, Relationship, SQLModel

from axile.common.trade_channel import TradeChannel
from axile.domain.strategy import Strategy, WeightType
from axile.server.db.models.base import now_str

if TYPE_CHECKING:
    from axile.server.db.models.account import PortfolioAccount


class StrategyConfigBase(SQLModel):
    """持久化策略配置的基础字段."""

    strategies: List[Strategy] = Field(
        sa_column=Column(SA_JSON, nullable=False),
        description="策略组合",
    )
    weight_type: Optional[WeightType] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="仓位类型：ts 为时序策略，cs 为截面策略；自定义组合为空",
    )


class StrategyConfig(StrategyConfigBase, AsyncAttrs, table=True):
    """策略组合的关系记录, 只加不修改."""

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        default=0,
        sa_column=Column(Integer, ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False),
    )
    created_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))

    portfolio: "Portfolio" = Relationship(
        sa_relationship=relationship(
            "Portfolio",
            back_populates="strategy_configs",
        )
    )


class StrategyConfigPublic(StrategyConfigBase):
    """策略配置记录的公开表示."""

    id: Optional[int]
    created_at: str


class StrategyConfigListPublic(SQLModel):
    """策略配置记录的列表响应封装."""

    data: List[StrategyConfigPublic]
    count: int


class PortfolioBase(SQLModel):
    """组合模型共用字段."""

    name: str = Field(sa_column=Column(Text, nullable=False), description="投资组合名称, 必填")
    market: str = Field(
        sa_column=Column(Text, nullable=False),
        description="交易市场标识, 例如: A股、加密货币、期货等, 必填",
    )
    description: Optional[str] = Field(
        sa_column=Column(Text, nullable=True),
        description="投资组合的描述信息, 用于介绍组合逻辑或目的, 非必填",
    )
    custom_calc_py_code: Optional[str] = Field(
        sa_column=Column(Text, nullable=True),
        description="自定义组合计算python脚本, 非必填",
    )
    status: Optional[str] = Field(
        sa_column=Column(Text, nullable=True),
        description="组合当前状态, 例如：启用、暂停、关闭, 非必填",
    )
    tag: Optional[str] = Field(
        sa_column=Column(Text, nullable=True),
        description="组合标签, 用于分类标记, 便于筛选和检索, 非必填",
    )


class Portfolio(PortfolioBase, AsyncAttrs, table=True):
    """组合."""

    id: Optional[int] = Field(default=None, primary_key=True)
    updated_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))
    created_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))

    strategy_configs: list[StrategyConfig] = Relationship(
        sa_relationship=relationship(
            "StrategyConfig",
            back_populates="portfolio",
            cascade="all, delete-orphan",
        )
    )
    account_records: list["PortfolioAccount"] = Relationship(
        sa_relationship=relationship(
            "PortfolioAccount",
            back_populates="portfolio",
            cascade="all, delete-orphan",
        )
    )


class PortfolioUpdate(SQLModel):
    """组合的局部更新载荷."""

    name: Optional[str] = None
    market: Optional[str] = None
    description: Optional[str] = None
    custom_calc_py_code: Optional[str] = None
    status: Optional[str] = None
    tag: Optional[str] = None
    strategies: Optional[List[Strategy]] = None
    weight_type: Optional[WeightType] = None


class PortfolioCreate(PortfolioBase):
    """创建组合及其初始策略配置时使用的载荷."""

    strategies: List[Strategy]
    weight_type: Optional[WeightType] = None


class PortfolioPreviewRequest(SQLModel):
    """试算组合目标权重的请求载荷.

    仅用于「不落库」地预览一份策略配置合成后的目标权重, 供编辑组合时的
    「前后对比」使用; 与 ``PortfolioCreate`` 不同, 它不涉及任何持久化。

    Attributes
    ----------
    strategies : List[Strategy]
        待试算的策略组合。
    trade_channel : TradeChannel
        计算目标所用的交易渠道。
    """

    strategies: List[Strategy]
    weight_type: WeightType
    trade_channel: TradeChannel


class ValidateCustomCalcRequest(SQLModel):
    """校验自定义组合脚本的请求载荷.

    仅用于「不落库、不下单」地执行一次用户脚本, 返回其计算出的目标权重或错误信息,
    供组合设置向导里的「Dry-run 验证 / 真实账户验证」使用。

    Attributes
    ----------
    custom_calc_py_code : str
        待校验的自定义组合脚本源码。
    account_id : Optional[int]
        指定时借该账户构造真实 ``Context`` 执行 (真实账户验证); 为空时使用样例
        上下文执行 (Dry-run)。
    """

    custom_calc_py_code: str
    account_id: Optional[int] = None


class ValidateCustomCalcResponse(SQLModel):
    """校验自定义组合脚本的响应载荷.

    Attributes
    ----------
    valid : bool
        脚本是否成功执行并返回结果。
    target : Optional[dict[str, float]]
        校验成功时脚本返回的 ``symbol -> 目标权重`` 映射。
    error : Optional[str]
        校验失败时的错误摘要 (``str(exc)``)。
    traceback : Optional[str]
        校验失败时的完整 traceback, 供前端「展开」查看。
    error_line : Optional[int]
        出错所在的用户代码行号 (1 基); 无法定位到用户代码时为 ``None``。
    error_offset : Optional[int]
        语法错误时的列偏移 (1 基); 其它情况为 ``None``。
    error_type : Optional[str]
        异常类型名, 例如 ``SyntaxError`` / ``RuntimeError``。
    error_message : Optional[str]
        简洁的错误消息, 供前端在出错行内联展示。
    """

    valid: bool
    target: Optional[dict[str, float]] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    error_line: Optional[int] = None
    error_offset: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class PortfolioPublic(PortfolioBase):
    """完整版组合信息,包含当前绑定的账户和当前策略."""

    id: Optional[int]
    updated_at: str
    created_at: str
    strategy_config: List[Strategy]
    weight_type: Optional[WeightType]
    account_id: Optional[int]


class PortfolioLitePublic(PortfolioBase):
    """简化版组合信息,不会加载关系."""

    id: Optional[int]
    updated_at: str
    created_at: str


class PortfolioListPublic(SQLModel):
    """轻量组合载荷的列表响应封装."""

    data: List[PortfolioLitePublic]


@event.listens_for(Portfolio, "before_update")
def update_portfolio_updated_at(_mapper: Mapper[Portfolio], _connection: Connection, target: Portfolio) -> None:
    """每次更新组合记录时刷新 ``updated_at``."""
    target.updated_at = now_str()

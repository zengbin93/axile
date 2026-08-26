"""账户与组合绑定数据库模型."""

import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import field_validator
from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Boolean, Column, Connection, Float, ForeignKey, Integer, Text, event
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import Mapper, relationship
from sqlmodel import Field, Relationship, SQLModel

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.models import AccountControlOverride
from axile.executor.models.unified_input import DEFAULT_EXECUTION_TIMEOUT_SECONDS
from axile.server.db.models.base import PydanticJSONType, now_str

if TYPE_CHECKING:
    from axile.server.db.models.account_asset import AccountAssetSnapshot
    from axile.server.db.models.execution import ExecuteRecord
    from axile.server.db.models.portfolio import Portfolio

# 账户级杠杆的通用粗粒度上限；更严格的渠道限制由渠道插件和执行器兜底。
_MAX_LEVERAGE = 125.0


def _validate_leverage(value: Optional[float]) -> Optional[float]:
    """
    校验杠杆倍数取值范围.

    Parameters
    ----------
    value : float | None
        杠杆倍数；``None``（未设置）与 ``0``（该方向不启用，如「做空杠杆 0 = 只做多」）均放行。

    Returns
    -------
    float | None
        原样返回入参，校验通过。

    Raises
    ------
    ValueError
        杠杆为负或超过 ``_MAX_LEVERAGE`` 时抛出，经 Pydantic 包装为 422。
    """
    if value is None:
        return value
    if value < 0:
        raise ValueError("杠杆必须是非负数")
    if value > _MAX_LEVERAGE:
        raise ValueError(f"杠杆不得超过 {_MAX_LEVERAGE:.0f} 倍")
    return value


_MAX_EXECUTION_TIMEOUT = 540
"""账户级执行总超时的上界（秒）。.

Notes
-----
上界的存在不是为了限制业务节奏，而是要挡住一个**顺序反转**：多进程 worker 后端
（当前为 GM 渠道）按账户总超时再加 60 秒 IPC 余量等待响应，超时后直接强杀 worker
进程。若不给内部 deadline 留返回窗口，执行会被记成通信失败而非 ``TERMINATED``，
审计里既看不到 ``trigger=timeout``，也拿不到本次执行的终止快照。账户上界取 540，
故 GM 调仓的 worker 外层等待最长为 600 秒。

下界取 ``1`` 而非 ``0``：``0`` 在执行器层是「不启用 deadline」的语义，而这道兜底防的是
「一次执行无限挂住账户运行占位」，允许按账户关掉就等于留了一个改一次便永久失效、且没有
任何告警的开关。仿真不受影响——仿真执行器在自己那层整体关闭 deadline。
"""


def _validate_cron_expr(value: Optional[str]) -> Optional[str]:
    """
    校验定时表达式可被解析.

    Parameters
    ----------
    value : str | None
        crontab 表达式（``|`` 可分隔多个）；``None`` / 空白表示「仅手动触发」，放行。

    Returns
    -------
    str | None
        原样返回入参，校验通过。

    Raises
    ------
    ValueError
        非空但无法解析为合法 crontab 时抛出，经 Pydantic 包装为 422，
        避免非法表达式落库后在「启动」时把调度器打挂。
    """
    from axile.server.cron import is_blank_cron_expr, parse_cron_expr

    if value is None or is_blank_cron_expr(value):
        return value
    parse_cron_expr(value)  # 无法解析会抛 ValueError
    return value


def _validate_algorithm_config(config: Optional[Dict[str, Any]], field_label: str) -> Optional[Dict[str, Any]]:
    """
    按算法注册表校验 ``{"method", "params"}`` 配置的参数是否越界.

    仅当 ``method`` 命中注册表且声明了 ``params_class`` 时才校验 ``params``；未知算法
    留给执行期处理（避免误伤插件/测试用的非注册算法）。

    Parameters
    ----------
    config : dict | None
        算法配置，形如 ``{"method": ..., "params": {...}}``；``None`` 直接放行。
    field_label : str
        字段中文名，用于错误信息（如「下单算法」「清仓算法」）。

    Returns
    -------
    dict | None
        原样返回入参，校验通过。

    Raises
    ------
    ValueError
        ``config`` 非对象、缺 ``method``，或 ``params`` 不满足算法参数模型约束（越界等）
        时抛出，经 Pydantic 包装为 422。
    """
    if config is None:
        return config
    if not isinstance(config, dict):
        raise ValueError(f"{field_label}必须是对象")
    method = config.get("method")
    if not method:
        raise ValueError(f"{field_label}缺少 method")
    params = config.get("params") or {}

    from pydantic import ValidationError

    from axile.executor.algorithms.core.base import get_algorithm_metadata

    try:
        meta = get_algorithm_metadata(str(method))
    except ValueError:
        # 未知算法：边界不拦，交由执行期校验，避免误伤未注册的插件/测试算法。
        return config
    if meta.params_class is not None:
        try:
            meta.params_class.model_validate(params)
        except ValidationError as exc:
            errors = exc.errors()
            detail = errors[0].get("msg", "") if errors else str(exc)
            raise ValueError(f"{field_label}参数不合法：{detail}") from exc
    return config


class AccountBase(SQLModel):
    """账户模型共用字段."""

    name: str = Field(sa_column=Column(Text, nullable=False), description="账户名称, 必填")
    market: str = Field(
        sa_column=Column(Text, nullable=False),
        description="交易市场标识, 例如: A股、加密货币、期货等, 必填",
    )
    trade_channel: TradeChannel = Field(
        sa_column=Column(Text, nullable=False),
        description="实盘渠道, 必填",
    )
    account_control_preset: str = Field(
        sa_column=Column(Text, nullable=False),
        description="账户控制 preset 标识, 必填",
    )
    account_control_override: AccountControlOverride | None = Field(
        default=None,
        sa_column=Column(PydanticJSONType(AccountControlOverride), nullable=True),
        description="账户控制的局部 override, 可选；支持 account/group 级规则与 operations.<op>.symbol 级规则",
    )
    account_config: Dict[str, Any] = Field(
        sa_column=Column(SA_JSON, nullable=False),
        description="账户配置, JSON格式, 包含登录信息、API密钥等, 必填",
    )
    is_started: bool = Field(
        sa_column=Column(Boolean, nullable=False),
        description="账户是否已启动, 布尔值, 必填",
    )
    cron_expr: str = Field(
        sa_column=Column(Text, nullable=False),
        description="定时任务表达式, 符合crontab语法, 必填",
    )
    remark: Optional[str] = Field(sa_column=Column(Text, nullable=True), description="账户备注信息, 可选")
    brokerage: str = Field(
        sa_column=Column(Text, nullable=False),
        description="券商名称, 例如华泰、银河等, 必填",
    )
    weight_precision: float = Field(
        sa_column=Column(Float, nullable=False),
        description="权重值的精度, 必须是10的负整数次幂, 默认: 0.01",
    )
    long_leverage: Optional[float] = Field(
        default=None,
        sa_column=Column(Float, nullable=True),
        description="做多杠杆",
    )
    short_leverage: Optional[float] = Field(
        default=None,
        sa_column=Column(Float, nullable=True),
        description="做空杠杆",
    )
    algorithm: Dict[str, Any] = Field(
        sa_column=Column(SA_JSON, nullable=True),
        description="下单算法,必填",
    )
    empty_positions_algorithm: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(SA_JSON, nullable=True),
        description="清仓算法, 非必填; null 时由执行逻辑回退到默认值",
    )
    trade_rules: Optional[Dict[str, Any]] = Field(
        sa_column=Column(SA_JSON, nullable=True),
        description="交易规则,非必填",
    )
    forbidden_symbols: Optional[List[str]] = Field(
        sa_column=Column(SA_JSON, nullable=True),
        description="禁用品种,非必填",
    )
    risk_symbols: Optional[List[str]] = Field(
        sa_column=Column(SA_JSON, nullable=True),
        description="风险品种,自动平仓,非必填",
    )
    feishu_key: Optional[str] = Field(sa_column=Column(Text, nullable=True), description="飞书KEY, 可选")
    portfolio_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("portfolio.id", ondelete="SET NULL"), nullable=True),
        description="当前绑定组合 ID（可空，删除组合时 DB 自动设为 NULL）",
    )
    write_empty_record: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
        description="是否写入空订单的执行记录, 0/1 或 null 表示不写入,只有设置1才写入, 默认不写入",
    )
    execution_timeout: int = Field(
        default=DEFAULT_EXECUTION_TIMEOUT_SECONDS,
        ge=1,
        le=_MAX_EXECUTION_TIMEOUT,
        sa_column=Column(Integer, nullable=False, server_default=str(DEFAULT_EXECUTION_TIMEOUT_SECONDS)),
        description=f"执行层总超时（秒）, 必填, 取值 1..{_MAX_EXECUTION_TIMEOUT}, 默认 {DEFAULT_EXECUTION_TIMEOUT_SECONDS}; 到点直接中断本次执行, 不等撤单",
    )

    @field_validator("long_leverage", "short_leverage")
    def _check_leverage_fields(cls, value: Optional[float]) -> Optional[float]:
        """校验多空杠杆取值范围."""
        return _validate_leverage(value)

    @field_validator("cron_expr")
    def _check_cron_expr(cls, value: Optional[str]) -> Optional[str]:
        """校验定时表达式可解析；空串（仅手动触发）放行."""
        return _validate_cron_expr(value)

    @field_validator("algorithm")
    def _check_algorithm_field(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """按注册表校验下单算法参数是否越界."""
        return _validate_algorithm_config(value, "下单算法")

    @field_validator("empty_positions_algorithm")
    def _check_empty_positions_algorithm_field(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """按注册表校验清仓算法参数是否越界."""
        return _validate_algorithm_config(value, "清仓算法")


class AccountCreate(AccountBase):
    """创建账户时使用的载荷."""


class Account(AccountBase, AsyncAttrs, table=True):
    """账户."""

    id: Optional[int] = Field(default=None, primary_key=True)
    updated_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))
    created_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))

    execute_records: list["ExecuteRecord"] = Relationship(
        sa_relationship=relationship(
            "ExecuteRecord",
            back_populates="account",
            cascade="all, delete-orphan",
        )
    )
    asset_snapshots: list["AccountAssetSnapshot"] = Relationship(
        sa_relationship=relationship(
            "AccountAssetSnapshot",
            back_populates="account",
            cascade="all, delete-orphan",
        )
    )
    portfolio_records: list["PortfolioAccount"] = Relationship(
        sa_relationship=relationship(
            "PortfolioAccount",
            back_populates="account",
            cascade="all, delete-orphan",
        )
    )

    @field_validator("weight_precision")
    def check_weight_precision(cls, value: Optional[float]) -> Optional[float]:
        """要求配置的权重精度必须是 10 的幂."""
        if value is None:
            return value
        if value <= 0:
            raise ValueError("weight_precision 必须是正数")
        log10_value = math.log10(value)
        if not log10_value.is_integer():
            raise ValueError("weight_precision 必须是10的负整数次幂, 如 1, 0.1, 0.01, 0.001")
        return value


class AccountPublic(AccountBase):
    """账户信息."""

    id: Optional[int]
    updated_at: str
    created_at: str


class AccountListPublic(SQLModel):
    """账户载荷的列表响应封装."""

    data: List[AccountPublic]


class AccountNextRunPublic(SQLModel):
    """账户未来调度执行时间的响应载荷.

    Attributes
    ----------
    account_id : int
        账户 ID。
    is_scheduled : bool
        当前是否存在对应的调度任务（账户已启动且已绑定组合时才有）。
    next_run_time : Optional[str]
        下一次执行时间的 ISO8601 字符串；无调度任务或任务无下次触发时为 ``None``。
    next_run_times : List[str]
        未来最多三次执行时间的 ISO8601 字符串，按时间升序排列。
    next_execution_times : List[str]
        按交易日历过滤后，未来最多三次实际执行时间。
    """

    account_id: int
    is_scheduled: bool
    next_run_time: Optional[str] = None
    next_run_times: List[str] = Field(default_factory=list)
    next_execution_times: List[str] = Field(default_factory=list)


class AccountDashboardItemPublic(SQLModel):
    """仪表盘聚合中的单账户项.

    一次性把舰队卡所需数据拼齐，避免前端对每个账户分别请求下次执行、执行记录等。
    权益与持仓取自该账户最近一次持久化的资产快照。

    Attributes
    ----------
    account_id : int
        账户 ID。
    name : str
        账户名称。
    market : str
        市场。
    trade_channel : TradeChannel
        交易渠道。
    is_started : bool
        是否已启动自动执行。
    portfolio_id : Optional[int]
        当前绑定的组合 ID；未绑定为 ``None``。
    is_scheduled : bool
        是否存在对应的调度任务。
    next_run_time : Optional[str]
        下一次执行时间的 ISO8601 字符串；无调度或无下次触发时为 ``None``。
    total_asset : float
        最近一次快照的账户总权益。
    currency : str
        权益计价币种。
    holdings_count : int
        最近一次快照的持仓品种数。
    position_weights : List[float]
        最近一次快照各持仓的市值（降序，最多 12 项），用于持仓分布条。
    equity_series : List[float]
        近端权益序列（按时间升序），用于迷你走势图。
    asset_observed_at : Optional[str]
        最近一次账户资产观测时间；无快照时为 ``None``。
    last_is_success : Optional[int]
        最近一次执行是否成功（1/0）；无记录时为 ``None``。
    last_exec_at : Optional[str]
        最近一次执行的时间戳；无记录时为 ``None``。
    running_execution_id : Optional[str]
        当前正在运行的执行链路标识；账户此刻无在途执行时为 ``None``。
        取自执行并发锁（唯一真源），使前端能看见调度器/他端发起的执行。
    running_kind : Optional[str]
        当前在途执行的种类（如 ``rebalance``/``clear_positions``）；无在途执行时为 ``None``。
    running_phase : Optional[str]
        当前在途执行的阶段标签（``triggered``/``snapshot``/``planning``/``executing``/
        ``settling`` 之一，见 :data:`axile.server.execution.live.PHASE_ORDER`）；无在途执行时为 ``None``。
    today_pct : Optional[float]
        「今日」权益涨跌百分比：``(当前权益 − 今日基准) / 今日基准 × 100``。基准取今天
        00:00 之前最后一条有效快照（昨收），无跨日数据时退回今天最早一条（今开）；无可用
        基准时为 ``None``。刻意在服务端按时间戳锚定自然日，而非由前端取序列末两点相减。
    """

    account_id: int
    name: str
    market: str
    trade_channel: TradeChannel
    is_started: bool
    portfolio_id: Optional[int] = None
    is_scheduled: bool
    next_run_time: Optional[str] = None
    total_asset: float
    currency: str
    holdings_count: int
    position_weights: List[float]
    equity_series: List[float]
    asset_observed_at: Optional[str] = None
    last_is_success: Optional[int] = None
    last_exec_at: Optional[str] = None
    running_execution_id: Optional[str] = None
    running_kind: Optional[str] = None
    running_phase: Optional[str] = None
    today_pct: Optional[float] = None


class AccountDashboardPublic(SQLModel):
    """仪表盘聚合响应.

    Attributes
    ----------
    data : List[AccountDashboardItemPublic]
        每个账户一项的聚合列表。
    """

    data: List[AccountDashboardItemPublic]


class AccountUpdate(SQLModel):
    """账户变更时使用的局部更新载荷."""

    name: Optional[str] = None
    market: Optional[str] = None
    trade_channel: Optional[TradeChannel] = None
    account_control_preset: Optional[str] = None
    account_control_override: AccountControlOverride | None = None
    account_config: Optional[Dict[str, Any]] = None
    is_started: Optional[bool] = None
    cron_expr: Optional[str] = None
    remark: Optional[str] = None
    brokerage: Optional[str] = None
    login_secret: Optional[str] = None
    weight_precision: Optional[float] = None
    long_leverage: Optional[float] = None
    short_leverage: Optional[float] = None
    algorithm: Optional[Dict[str, Any]] = None
    empty_positions_algorithm: Optional[Dict[str, Any]] = None
    trade_rules: Optional[Dict[str, Any]] = None
    forbidden_symbols: Optional[List[str]] = None
    feishu_key: Optional[str] = None
    portfolio_id: Optional[int] = None
    write_empty_record: Optional[int] = None
    execution_timeout: Optional[int] = Field(default=None, ge=1, le=_MAX_EXECUTION_TIMEOUT)

    @field_validator("long_leverage", "short_leverage")
    def _check_leverage_fields(cls, value: Optional[float]) -> Optional[float]:
        """校验多空杠杆取值范围."""
        return _validate_leverage(value)

    @field_validator("cron_expr")
    def _check_cron_expr(cls, value: Optional[str]) -> Optional[str]:
        """校验定时表达式可解析；空串（仅手动触发）放行."""
        return _validate_cron_expr(value)

    @field_validator("algorithm")
    def _check_algorithm_field(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """按注册表校验下单算法参数是否越界."""
        return _validate_algorithm_config(value, "下单算法")

    @field_validator("empty_positions_algorithm")
    def _check_empty_positions_algorithm_field(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """按注册表校验清仓算法参数是否越界."""
        return _validate_algorithm_config(value, "清仓算法")


class PortfolioAccountBase(SQLModel):
    """账户与组合绑定历史记录的共用字段."""

    account_id: int = Field(sa_column=Column(Integer, ForeignKey("account.id", ondelete="CASCADE"), nullable=False))
    portfolio_id: Optional[int] = Field(
        sa_column=Column(Integer, ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=True)
    )
    created_at: str = Field(default_factory=now_str, sa_column=Column(Text, nullable=False))


class PortfolioAccount(PortfolioAccountBase, AsyncAttrs, table=True):
    """账户和组合的记录, 只加不修改."""

    id: Optional[int] = Field(default=None, primary_key=True)

    account: Account = Relationship(
        sa_relationship=relationship(
            "Account",
            back_populates="portfolio_records",
        )
    )
    portfolio: Optional["Portfolio"] = Relationship(
        sa_relationship=relationship(
            "Portfolio",
            back_populates="account_records",
        )
    )


class PortfolioAccountPublic(PortfolioAccountBase):
    """账户与组合绑定记录的公开表示."""


class PortfolioAccountListPublic(SQLModel):
    """账户与组合绑定记录的列表响应封装."""

    data: List[PortfolioAccountPublic]
    count: int


@event.listens_for(Account, "before_update")
def update_account_updated_at(_mapper: Mapper[Account], _connection: Connection, target: Account) -> None:
    """每次更新账户记录时刷新 ``updated_at``."""
    target.updated_at = now_str()

"""
算法参数模型公共基础类.

提供所有算法参数的基础类和混入类，包含完整的参数验证规则。
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class BaseAlgorithmParams(BaseModel):
    """
    定义所有算法共享的基础参数。

    Notes
    -----
    该基类只放跨算法都适用的运行时约束，避免渠道或策略特有参数污染所有
    参数模型的公共接口。
    """

    max_wait_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        title="单次最大等待",
        description="最大等待时间（秒），范围：1-3600",
    )

    @field_validator("max_wait_seconds")
    @classmethod
    def validate_max_wait_seconds(cls, v: int) -> int:
        """
        验证最大等待时间。

        Parameters
        ----------
        v : int
            调用方传入的最大等待秒数。

        Returns
        -------
        int
            通过字段边界校验后的等待秒数。

        Notes
        -----
        这里故意不再叠加“建议值”一类软限制；超过建议值的合法配置仍允许进入
        执行阶段，由调用方按具体渠道和策略自行决定是否记录告警。
        """
        return v

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        return f"BaseAlgorithmParams(max_wait_seconds={self.max_wait_seconds})"


class ChaseParamsMixin(BaseModel):
    """
    为算法参数补充追单相关配置。

    Notes
    -----
    该 mixin 同时承担两类约束：字段级的基础范围校验，以及多字段联动的
    一致性校验。后者主要用于拦截会显著放大成交滑点、运行时长或交易所限频
    风险的配置组合。
    """

    chase_enabled: bool = Field(
        default=False,
        title="追单",
        description="是否启用追单",
    )
    chase_ticks: int = Field(
        default=1,
        ge=0,
        title="价格偏离",
        description="价格偏离多少跳后追单",
    )
    max_chase_count: int = Field(
        default=5,
        ge=0,
        title="最大追单次数",
        description="单个订单最大追单次数",
    )
    chase_interval: float = Field(
        default=5.0,
        ge=0.0,
        title="追单间隔",
        description="追单间隔（秒）",
    )

    @field_validator("chase_ticks")
    @classmethod
    def validate_chase_ticks(cls, v: int, info: Any) -> int:
        """
        校验追单位数的兼容性边界。

        Parameters
        ----------
        v : int
            当前配置的追单位数。
        info : Any
            Pydantic 提供的同模型字段上下文。

        Returns
        -------
        int
            原样返回的追单位数。

        Notes
        -----
        ``chase_ticks > 20`` 在经验上已经偏激进，但历史配置里可能存在这类值。
        这里保留校验钩子而不升级为硬错误，避免仅因参数回放就破坏兼容性。
        """
        return v

    @model_validator(mode="after")
    def validate_chase_consistency(self) -> "ChaseParamsMixin":
        """
        校验追单参数的组合约束。

        Returns
        -------
        ChaseParamsMixin
            当前通过一致性校验的参数对象。

        Raises
        ------
        ValueError
            启用追单后，任一参数组合超出算法允许的风险边界时抛出。

        Notes
        -----
        这里的限制不是随意的样式偏好，而是为了在参数层就阻断明显危险的组合：
        例如运行时长过久、追单过于频繁，或单次价格追逐过激进。
        """
        if not self.chase_enabled:
            return self

        if self.chase_ticks < 1:
            raise ValueError(f"启用追单时，追单位数必须 >= 1，当前为 {self.chase_ticks}")

        if self.max_chase_count < 1:
            raise ValueError(f"启用追单时，追单次数必须 >= 1，当前为 {self.max_chase_count}")

        if self.chase_interval < 0.1:
            raise ValueError(f"启用追单时，追单间隔必须 >= 0.1秒，当前为 {self.chase_interval}")

        # 这些硬上限主要防止把一次追单流程配置成“极慢”或“极密”，从而在
        # 真实交易里放大运行时长、滑点和限频风险。
        if self.chase_ticks > 100:
            raise ValueError(f"追单位数（{self.chase_ticks}）过大，不应该超过100跳。")

        if self.max_chase_count > 50:
            raise ValueError(f"追单次数（{self.max_chase_count}）过多，不应该超过50次。")

        if self.chase_interval > 300:
            raise ValueError(f"追单间隔（{self.chase_interval}秒）过长，不应该超过300秒（5分钟）。")

        total_chase_time = self.max_chase_count * self.chase_interval

        if total_chase_time > 600:
            raise ValueError(
                f"追单总时间（max_chase_count * chase_interval = {total_chase_time}秒）"
                f"过长，可能导致算法运行时间过长。"
                f"请减少 max_chase_count 或 chase_interval，使总时间不超过600秒。"
            )

        if self.chase_interval < 1.0 and self.max_chase_count > 10:
            raise ValueError(
                f"追单间隔（{self.chase_interval}秒）过短且追单次数过多，"
                f"可能触发交易所速率限制。请增加追单间隔（>=1.0秒）或减少追单次数（<=10）。"
            )

        return self

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        if not self.chase_enabled:
            return "ChaseParamsMixin(chase_enabled=False)"
        return (
            f"ChaseParamsMixin("
            f"enabled={self.chase_enabled}, "
            f"ticks={self.chase_ticks}, "
            f"max_count={self.max_chase_count}, "
            f"interval={self.chase_interval})"
        )

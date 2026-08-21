"""
统一输入模型使用的账户配置定义.

按交易渠道拆分账户配置模型，避免 ``UnifiedStandardInput`` 主文件同时承载
账户字段定义与输入构造规则。
"""

from __future__ import annotations

from typing import override

from pydantic import BaseModel, ConfigDict, Field, model_validator

from axile.common.trade_channel import TradeChannel


def _channel_value(channel: object) -> str:
    """
    返回用于日志与序列化的规范化渠道字符串.

    Parameters
    ----------
    channel : object
        渠道对象或原始渠道值。

    Returns
    -------
    str
        规范化后的渠道字符串。
    """
    channel_value = getattr(channel, "value", None)
    if isinstance(channel_value, str):
        return channel_value
    return str(channel)


class BaseAccountConfig(BaseModel):
    """
    基础账户配置抽象模型.

    Attributes
    ----------
    channel_type : TradeChannel
        账户所属的交易渠道类型。
    """

    model_config = ConfigDict(extra="allow")

    channel_type: TradeChannel = Field(..., description="交易渠道类型")

    @override
    def __str__(self) -> str:
        """返回便于记录日志的简要字符串表示."""
        return f"{_channel_value(self.channel_type)}AccountConfig"


class CTPAccountConfig(BaseAccountConfig):
    """
    CTP 期货账户配置.

    Attributes
    ----------
    broker_id : str
        经纪公司代码。
    investor_id : str
        投资者代码。
    password : str
        登录密码。
    """

    model_config = ConfigDict(extra="allow")

    broker_id: str = Field(..., description="经纪公司代码")
    investor_id: str = Field(..., description="投资者代码")
    password: str = Field(..., description="密码")

    td_front: str | None = Field(None, description="交易服务器地址")
    md_front: str | None = Field(None, description="行情服务器地址")
    product_info: str | None = Field(None, description="产品信息")
    auth_code: str | None = Field(None, description="认证码")
    app_id: str | None = Field(None, description="应用ID")

    @model_validator(mode="before")
    @classmethod
    def set_channel_type(cls, data: dict[str, object] | BaseAccountConfig) -> dict[str, object] | BaseAccountConfig:
        """
        在预校验阶段补齐渠道类型.

        Parameters
        ----------
        data : dict[str, object] | BaseAccountConfig
            原始账户配置数据或已构造的账户对象。

        Returns
        -------
        dict[str, object] | BaseAccountConfig
            补齐 ``channel_type`` 后的数据对象。
        """
        if not isinstance(data, dict):
            return data
        data["channel_type"] = TradeChannel.CTP
        return data


class GMAccountConfig(BaseAccountConfig):
    """
    掘金账户配置.

    Attributes
    ----------
    account_id : str
        掘金账户标识。
    token : str
        掘金终端令牌。
    terminal_path : str | None
        本地终端路径。
    serv_addr : str | None
        远程服务地址。
    """

    model_config = ConfigDict(extra="allow")

    account_id: str = Field(..., description="掘金账户ID")
    token: str = Field(..., description="掘金终端令牌")
    terminal_path: str | None = Field(None, description="掘金终端目录")
    serv_addr: str | None = Field(None, description="掘金服务地址")

    @model_validator(mode="before")
    @classmethod
    def set_channel_type(cls, data: dict[str, object] | BaseAccountConfig) -> dict[str, object] | BaseAccountConfig:
        """
        在预校验阶段补齐渠道类型.

        Parameters
        ----------
        data : dict[str, object] | BaseAccountConfig
            原始账户配置数据或已构造的账户对象。

        Returns
        -------
        dict[str, object] | BaseAccountConfig
            补齐 ``channel_type`` 后的数据对象。
        """
        if not isinstance(data, dict):
            return data
        data["channel_type"] = TradeChannel.GM
        return data

    @model_validator(mode="after")
    def validate_connection_target(self) -> "GMAccountConfig":
        """
        校验连接目标配置是否合法.

        Returns
        -------
        GMAccountConfig
            校验通过后的当前账户配置对象。

        Raises
        ------
        ValueError
            当 ``terminal_path`` 与 ``serv_addr`` 同时为空或同时存在时抛出。
        """
        if (self.terminal_path is None) == (self.serv_addr is None):
            raise ValueError("terminal_path 和 serv_addr 必须且只能设置一个")
        return self


AccountConfig = BaseAccountConfig

"""定义开放的交易渠道标识类型."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class TradeChannel(str):
    """
    表示可由运行时插件扩展的交易渠道标识.

    与封闭枚举不同，该类型接受任意非空字符串，因此未被公开核心预先知晓的
    渠道也能通过 API 校验并持久化。内置渠道常量仅用于兼容现有调用代码，
    可用渠道的真实目录由 :mod:`axile.channels` 注册表维护。

    Attributes
    ----------
    CTP : TradeChannel
        CTP 渠道标识。
    QMT : TradeChannel
        QMT 渠道标识。
    GM : TradeChannel
        掘金量化渠道标识。
    """

    CTP: ClassVar[TradeChannel]
    QMT: ClassVar[TradeChannel]
    GM: ClassVar[TradeChannel]

    def __new__(cls, value: object) -> TradeChannel:
        """
        创建规范化的渠道标识.

        Parameters
        ----------
        value : object
            原始渠道值；枚举兼容对象可通过 ``value`` 属性提供字符串。

        Returns
        -------
        TradeChannel
            去除首尾空白并转为小写的渠道标识。

        Raises
        ------
        ValueError
            原始值不是字符串或字符串为空时抛出。
        """
        raw_value = getattr(value, "value", value)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("交易渠道标识必须是非空字符串")
        return super().__new__(cls, raw_value.strip().lower())

    @property
    def value(self) -> str:
        """返回与历史枚举接口兼容的字符串值."""
        return str(self)

    @property
    def name(self) -> str:
        """返回适合日志展示的规范化渠道名称."""
        return str(self).replace("-", "_").upper()

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        """
        返回开放字符串对应的 Pydantic 核心校验模式.

        Parameters
        ----------
        _source_type : Any
            Pydantic 请求生成模式的源类型。
        _handler : GetCoreSchemaHandler
            Pydantic 模式生成处理器。

        Returns
        -------
        CoreSchema
            接受非空字符串并构造 ``TradeChannel`` 的核心模式。
        """
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(min_length=1),
            serialization=core_schema.to_string_ser_schema(),
        )


TradeChannel.CTP = TradeChannel("ctp")
TradeChannel.QMT = TradeChannel("qmt")
TradeChannel.GM = TradeChannel("gm")

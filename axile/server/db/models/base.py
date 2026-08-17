"""服务端数据库模型共享基础定义."""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import JSON as SA_JSON
from sqlalchemy.types import TypeDecorator


class PydanticJSONType(TypeDecorator[Any]):
    """将 Pydantic 模型安全地存入 JSON 列."""

    impl = SA_JSON
    cache_ok = True

    def __init__(self, model_type: type[BaseModel]) -> None:
        super().__init__()
        self.model_type = model_type

    def process_bind_param(self, value: Any, _dialect: Any) -> Any:
        """
        在写入数据库前将 Pydantic 模型转换为 JSON 兼容对象.

        Parameters
        ----------
        value : Any
            待写入 JSON 列的原始值。
        _dialect : Any
            当前数据库方言对象；此处不直接使用。

        Returns
        -------
        Any
            若输入为 Pydantic 模型则返回其 JSON 化字典，否则原样返回。
        """
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value

    def process_result_value(self, value: Any, _dialect: Any) -> Any:
        """
        在读取数据库结果后恢复为声明的 Pydantic 模型.

        Parameters
        ----------
        value : Any
            从 JSON 列读取出的原始值。
        _dialect : Any
            当前数据库方言对象；此处不直接使用。

        Returns
        -------
        Any
            ``None`` 原样返回；其他值会按目标 Pydantic 模型校验并构造实例。
        """
        if value is None:
            return None
        return self.model_type.model_validate(value)


def now_str() -> str:
    """返回不带微秒的本地时间 ISO 字符串."""
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def now_ms() -> int:
    """返回当前时间的 Unix 毫秒时间戳."""
    return time.time_ns() // 1_000_000


def new_execution_id() -> str:
    """返回一个随机 execution 标识."""
    return uuid.uuid4().hex

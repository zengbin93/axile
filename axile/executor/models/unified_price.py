"""
统一价格快照模型.

定义执行器内部通用的行情快照结构，统一提供一档到五档买卖价量字段，并通过
``extra`` 保留渠道特有数据。
"""

from datetime import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field
from typing_extensions import override

# ExtraData用于存储渠道特有的数据，使用Any是合理的
# 因为不同渠道可能有不同类型的数据需要存储
# type: ignore[reportExplicitAny]
ExtraData = dict[str, Any]


class UnifiedPriceData(BaseModel):
    """
    统一价格快照模型.

    Attributes
    ----------
    symbol : str
        品种代码。
    last_price : float
        最新成交价。
    bid_price : float
        买一价。
    ask_price : float
        卖一价。
    volume : float
        当前成交量字段。
    timestamp : int
        毫秒级时间戳。
    extra : ExtraData
        渠道特有扩展字段。
    """

    model_config = ConfigDict(
        use_enum_values=True,
        validate_default=False,
        validate_assignment=False,
        extra="ignore",
    )

    # 核心字段（所有渠道都有）
    symbol: str = Field(..., description="品种代码（统一格式）")
    last_price: float = Field(..., description="最新价")

    # 五档买卖价格（统一包含5档）
    bid_price: float = Field(..., description="买一价")
    bid_price_2: float = Field(default=0.0, description="买二价")
    bid_price_3: float = Field(default=0.0, description="买三价")
    bid_price_4: float = Field(default=0.0, description="买四价")
    bid_price_5: float = Field(default=0.0, description="买五价")

    ask_price: float = Field(..., description="卖一价")
    ask_price_2: float = Field(default=0.0, description="卖二价")
    ask_price_3: float = Field(default=0.0, description="卖三价")
    ask_price_4: float = Field(default=0.0, description="卖四价")
    ask_price_5: float = Field(default=0.0, description="卖五价")

    # 五档买卖量（统一包含5档）
    bid_volume: float = Field(..., description="买一量")
    bid_volume_2: float = Field(default=0.0, description="买二量")
    bid_volume_3: float = Field(default=0.0, description="买三量")
    bid_volume_4: float = Field(default=0.0, description="买四量")
    bid_volume_5: float = Field(default=0.0, description="买五量")

    ask_volume: float = Field(..., description="卖一量")
    ask_volume_2: float = Field(default=0.0, description="卖二量")
    ask_volume_3: float = Field(default=0.0, description="卖三量")
    ask_volume_4: float = Field(default=0.0, description="卖四量")
    ask_volume_5: float = Field(default=0.0, description="卖五量")

    # 其他核心字段
    volume: float = Field(..., description="成交量")
    turnover: float = Field(default=0.0, description="成交额")
    timestamp: int = Field(..., description="时间戳（毫秒）")
    update_time: str = Field(..., description="更新时间（ISO格式）")

    # 盘口有效性标记
    book_valid: bool = Field(
        default=True,
        description="买卖一是否为真实盘口命中；False 表示用 last_price 兜底的假盘口，下游不应据此挂 maker 价",
    )

    # 渠道特有数据
    extra: ExtraData = Field(default={}, description="渠道特有数据，包含原始数据和渠道特定字段")

    @override
    def __str__(self) -> str:
        """返回便于记录日志的简要字符串表示."""
        return (
            f"UnifiedPriceData(symbol={self.symbol}, "
            f"last={self.last_price}, bid={self.bid_price}, ask={self.ask_price})"
        )

    def get_spread(self) -> float:
        """
        计算买一与卖一之间的价差.

        Returns
        -------
        float
            当前买卖价差。
        """
        return self.ask_price - self.bid_price

    def get_mid_price(self) -> float:
        """
        计算买一与卖一之间的中间价.

        Returns
        -------
        float
            当前盘口中间价。
        """
        return (self.bid_price + self.ask_price) / 2.0

    def is_valid(self) -> bool:
        """
        检查当前行情快照是否有效.

        Returns
        -------
        bool
            当关键价格与时间字段有效时返回 ``True``。
        """
        return (
            self.last_price > 0
            and self.bid_price > 0
            and self.ask_price > 0
            and self.bid_price <= self.ask_price
            and self.timestamp > 0
        )

    def get_all_bid_prices(self) -> list[float]:
        """
        返回所有买方价格档位.

        Returns
        -------
        list[float]
            按档位顺序排列的买价列表。
        """
        return [
            self.bid_price,
            self.bid_price_2,
            self.bid_price_3,
            self.bid_price_4,
            self.bid_price_5,
        ]

    def get_all_ask_prices(self) -> list[float]:
        """
        返回所有卖方价格档位.

        Returns
        -------
        list[float]
            按档位顺序排列的卖价列表。
        """
        return [
            self.ask_price,
            self.ask_price_2,
            self.ask_price_3,
            self.ask_price_4,
            self.ask_price_5,
        ]

    def get_all_bid_volumes(self) -> list[float]:
        """
        返回所有买方数量档位.

        Returns
        -------
        list[float]
            按档位顺序排列的买量列表。
        """
        return [
            self.bid_volume,
            self.bid_volume_2,
            self.bid_volume_3,
            self.bid_volume_4,
            self.bid_volume_5,
        ]

    def get_all_ask_volumes(self) -> list[float]:
        """
        返回所有卖方数量档位.

        Returns
        -------
        list[float]
            按档位顺序排列的卖量列表。
        """
        return [
            self.ask_volume,
            self.ask_volume_2,
            self.ask_volume_3,
            self.ask_volume_4,
            self.ask_volume_5,
        ]

    def get_price_levels(self, depth: int = 5) -> dict[str, list[float]]:
        """
        获取指定深度的买卖价格与数量.

        Parameters
        ----------
        depth : int, default=5
            需要提取的盘口深度，最大支持五档。

        Returns
        -------
        dict[str, list[float]]
            包含买卖价格和数量切片的字典。
        """
        actual_depth = min(max(1, depth), 5)

        return {
            "bid_prices": self.get_all_bid_prices()[:actual_depth],
            "ask_prices": self.get_all_ask_prices()[:actual_depth],
            "bid_volumes": self.get_all_bid_volumes()[:actual_depth],
            "ask_volumes": self.get_all_ask_volumes()[:actual_depth],
        }

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timestamp_datetime(self) -> dt:
        """
        将毫秒时间戳转换为 ``datetime`` 对象.

        Returns
        -------
        dt
            由 ``timestamp`` 推导出的时间对象。
        """
        return dt.fromtimestamp(self.timestamp / 1000.0)

    def to_dict(self) -> dict[str, Any]:
        """
        导出为普通字典.

        Returns
        -------
        dict[str, Any]
            适合序列化或调试输出的字典结果。
        """
        return self.model_dump()


def clone_price_data(price_data: UnifiedPriceData | None) -> UnifiedPriceData | None:
    """
    深拷贝一份价格快照.

    Parameters
    ----------
    price_data : UnifiedPriceData | None
        待复制的价格快照对象。

    Returns
    -------
    UnifiedPriceData | None
        深拷贝后的价格快照；输入为 ``None`` 时返回 ``None``。
    """
    if price_data is None:
        return None
    return price_data.model_copy(deep=True)

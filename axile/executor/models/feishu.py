"""飞书账户通知卡片配置模型."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

_MAX_CUSTOM_CARD_BYTES = 20 * 1024
_MAX_CUSTOM_CARD_DEPTH = 20


def _json_depth(value: object) -> int:
    """返回 JSON 兼容值的最大嵌套深度."""
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


class FeishuCardConfig(BaseModel):
    """账户执行结果通知的自定义卡片配置."""

    mode: Literal["template", "custom"]
    template_id: str | None = Field(default=None, max_length=128)
    card: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_mode_payload(self) -> "FeishuCardConfig":
        """确保所选模式只携带对应的有效载荷."""
        if self.mode == "template":
            template_id = (self.template_id or "").strip()
            if not template_id:
                raise ValueError("飞书模板 ID 不能为空")
            self.template_id = template_id
            self.card = None
            return self

        if self.card is None:
            raise ValueError("自定义卡片内容不能为空")
        if "msg_type" in self.card or "card" in self.card:
            raise ValueError("请只粘贴飞书卡片主体，不要包含 webhook 消息信封")
        encoded = json.dumps(self.card, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > _MAX_CUSTOM_CARD_BYTES:
            raise ValueError("自定义卡片内容不得超过 20 KiB")
        if _json_depth(self.card) > _MAX_CUSTOM_CARD_DEPTH:
            raise ValueError("自定义卡片嵌套不得超过 20 层")
        self.template_id = None
        return self

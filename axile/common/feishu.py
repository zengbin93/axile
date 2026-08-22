"""飞书自定义机器人最小 HTTP 客户端."""

from typing import Any, Final, cast

import requests

_FEISHU_HOOK_BASE: Final = "https://open.feishu.cn/open-apis/bot/v2/hook/"
_FEISHU_TIMEOUT_SECONDS: Final = 15


def push_feishu_card(card: dict[str, object], key: str) -> None:
    """向飞书自定义机器人发送交互卡片.

    Parameters
    ----------
    card : dict[str, object]
        飞书交互卡片内容。
    key : str
        飞书群自定义机器人 webhook key。

    Raises
    ------
    requests.RequestException
        网络请求失败或 HTTP 状态异常。
    RuntimeError
        飞书响应无法解析，或响应体表示发送失败。
    """
    response = requests.post(
        f"{_FEISHU_HOOK_BASE}{key}",
        json=cast(Any, {"msg_type": "interactive", "card": card}),
        timeout=_FEISHU_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("飞书返回了无法解析的响应") from exc

    if isinstance(result, dict) and (result.get("code") == 0 or result.get("StatusMessage") == "success"):
        return

    detail = result.get("msg") or result.get("StatusMessage") or result if isinstance(result, dict) else result
    raise RuntimeError(f"飞书返回失败: {str(detail)[:200]}")

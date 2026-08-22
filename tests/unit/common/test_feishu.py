"""飞书自定义机器人 HTTP 客户端测试."""

from typing import Any

import pytest
import requests

from axile.common import feishu


class _Response:
    """提供 requests.Response 最小测试替身."""

    def __init__(self, payload: Any = None, *, json_error: Exception | None = None) -> None:
        self.payload = payload
        self.json_error = json_error
        self.raise_error: Exception | None = None

    def raise_for_status(self) -> None:
        """模拟 HTTP 状态校验."""
        if self.raise_error is not None:
            raise self.raise_error

    def json(self) -> Any:
        """返回响应体或模拟 JSON 解析失败."""
        if self.json_error is not None:
            raise self.json_error
        return self.payload


@pytest.mark.parametrize("payload", [{"code": 0, "msg": "success"}, {"StatusMessage": "success"}])
def test_push_feishu_card_accepts_supported_success_responses(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """新旧飞书成功响应都应被接受，并保持请求契约."""
    calls: list[tuple[str, dict[str, object], int]] = []

    def _post(url: str, *, json: dict[str, object], timeout: int) -> _Response:
        calls.append((url, json, timeout))
        return _Response(payload)

    monkeypatch.setattr(feishu.requests, "post", _post)
    card = {"type": "template", "data": {"template_id": "tpl"}}

    feishu.push_feishu_card(card, "hook-key")

    assert calls == [
        (
            "https://open.feishu.cn/open-apis/bot/v2/hook/hook-key",
            {"msg_type": "interactive", "card": card},
            15,
        )
    ]


def test_push_feishu_card_propagates_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 错误应抛给调用层记录."""
    response = _Response()
    response.raise_error = requests.HTTPError("503")
    monkeypatch.setattr(feishu.requests, "post", lambda *_args, **_kwargs: response)

    with pytest.raises(requests.HTTPError, match="503"):
        feishu.push_feishu_card({}, "hook-key")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_Response(json_error=ValueError("invalid json")), "无法解析"),
        (_Response({"code": 19001, "msg": "invalid access token"}), "invalid access token"),
    ],
)
def test_push_feishu_card_rejects_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response,
    message: str,
) -> None:
    """无法解析或业务失败的响应应转成明确异常."""
    monkeypatch.setattr(feishu.requests, "post", lambda *_args, **_kwargs: response)

    with pytest.raises(RuntimeError, match=message):
        feishu.push_feishu_card({}, "hook-key")

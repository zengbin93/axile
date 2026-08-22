"""服务端飞书错误通知测试."""

import asyncio

import pytest

from axile.server import error_notifications


def test_send_feishu_error_uses_internal_card_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """错误通知应通过内部发送器发送构造后的卡片."""
    pushed: list[tuple[dict[str, object], str]] = []

    async def _external_ip() -> str:
        return "1.2.3.4"

    def _push(card: dict[str, object], key: str) -> None:
        pushed.append((card, key))

    monkeypatch.setattr(error_notifications, "get_external_ip", _external_ip)
    monkeypatch.setattr(error_notifications, "push_feishu_card", _push)

    asyncio.run(error_notifications.send_feishu_error(RuntimeError("boom"), None, "hook-error"))

    assert len(pushed) == 1
    card, key = pushed[0]
    assert key == "hook-error"
    assert card["header"]["template"] == "red"  # type: ignore[index]
    assert "boom" in str(card["elements"])


def test_send_feishu_error_logs_sender_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """通知发送失败应记日志且不影响执行异常处理链路."""
    errors: list[str] = []

    async def _external_ip() -> str:
        return ""

    def _push(_card: dict[str, object], _key: str) -> None:
        raise RuntimeError("webhook unavailable")

    monkeypatch.setattr(error_notifications, "get_external_ip", _external_ip)
    monkeypatch.setattr(error_notifications, "push_feishu_card", _push)
    monkeypatch.setattr(error_notifications.loguru.logger, "error", lambda message: errors.append(str(message)))

    asyncio.run(error_notifications.send_feishu_error(RuntimeError("boom"), None, "hook-error"))

    assert errors == ["发送飞书错误通知失败: webhook unavailable"]

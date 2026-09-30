"""服务端飞书错误通知测试."""

import asyncio

import pytest

from axile.server import error_notifications


@pytest.fixture(autouse=True)
def isolate_notification_state(monkeypatch):
    monkeypatch.setattr(error_notifications, "record_system_notification_result", lambda _state: None)


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


def test_system_notification_runs_async_entry(monkeypatch, tmp_path) -> None:
    output = tmp_path / "system-notification.txt"
    code = f"""import asyncio
from pathlib import Path
async def notify(context):
    await asyncio.sleep(0)
    assert context['event_type'] == 'execution_error'
    assert context['execution_id'] == 'run-1'
    Path({str(output)!r}).write_text(context['error']['message'])
"""
    monkeypatch.setattr(error_notifications.settings, "system_execution_notification_mode", "function")
    monkeypatch.setattr(error_notifications.settings, "system_execution_notification_code", code)
    asyncio.run(error_notifications.send_feishu_error(RuntimeError("boom"), None, "", execution_id="run-1"))
    assert output.read_text() == "boom"

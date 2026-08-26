"""``axile.server.core.log_config`` 日志格式与上下文助手测试."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from axile.common.logging import LogComponent
from axile.common.trade_channel import TradeChannel
from axile.server.core import log_config
from axile.server.core.log_config import (
    _component_label,
    _context_label,
    _format_record,
    _json_format_record,
    execution_log_context,
)


def _record(
    *,
    name: str | None = "axile.executor.algorithms.utils.order_tracker",
    extra: dict[str, object] | None = None,
    exception: object | None = None,
) -> dict[str, object]:
    """构造同时满足控制台与 JSON formatter 的最小 Loguru record."""

    class _Level:
        name = "INFO"

    return {
        "time": datetime.fromisoformat("2026-08-25T13:50:53.146+08:00"),
        "level": _Level(),
        "name": name,
        "module": "order_tracker",
        "message": "定时查询完成: pending=1",
        "extra": extra or {},
        "file": SimpleNamespace(path="/workspace/order_tracker.py"),
        "function": "_query_pending_orders",
        "line": 571,
        "process": SimpleNamespace(id=1234, name="MainProcess"),
        "thread": SimpleNamespace(id=5678, name="ctp-symbol-algo_0"),
        "exception": exception,
    }


def test_execution_log_context_expands_channel_and_symbol() -> None:
    """执行上下文应展开渠道枚举并保留 symbol."""
    ctx = execution_log_context(
        account_id=1,
        account_name="测试网",
        channel=TradeChannel.CTP,
        execution_id="abc123",
        symbol="CF2701",
    )
    assert ctx == {
        "account_id": 1,
        "account_name": "测试网",
        "channel": TradeChannel.CTP.value,
        "execution_id": "abc123",
        "symbol": "CF2701",
    }


def test_execution_log_context_defaults_to_none() -> None:
    """未提供的字段应为 ``None``，由 formatter 统一跳过."""
    assert execution_log_context() == {
        "account_id": None,
        "account_name": None,
        "channel": None,
        "execution_id": None,
        "symbol": None,
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("axile.executor.algorithms.utils.order_tracker", "订单"),
        ("axile.executor.algorithms.defaults.twap.impl", "算法"),
        ("axile.executor.ctp.ctp_execute", "CTP"),
        ("axile.executor.gm.gm_execute", "掘金"),
        ("axile.executor.tq.tq_execute", "天勤"),
        ("axile.server.api.routes.account_crud", "接口"),
        ("axile.server.execution.worker_backend.worker", "任务"),
        ("axile.server.execution.scheduler", "调度"),
        ("axile.server.execution_audit", "审计"),
        ("apscheduler.executors.default", "调度"),
        ("apscheduler.scheduler", "调度"),
        ("sqlalchemy.engine", "数据库"),
        ("uvicorn.error", "服务"),
        ("third_party.client", "外部"),
    ],
)
def test_component_label_routes_runtime_modules(name: str, expected: str) -> None:
    """所有运行包与拦截 logger 都应归入稳定业务组件."""
    assert _component_label(name, {}) == expected


def test_component_label_prefers_explicit_binding() -> None:
    """显式组件用于动态算法等无法按模块路径归类的调用方."""
    assert _component_label("custom_package.algo", {"component": LogComponent.ALGORITHM}) == "算法"


def test_context_label_renders_human_readable_context() -> None:
    """账户名称、ID、渠道、symbol 与短 execution ID 应紧凑呈现."""
    label = _context_label(
        {
            "account_id": 1,
            "account_name": "测试网",
            "channel": "ctp",
            "symbol": "CF2701",
            "execution_id": "0e7a80e92bc94d38",
        }
    )
    assert label == "[测试网#1 ctp CF2701 0e7a80e9] "


def test_context_label_handles_id_only_and_empty_context() -> None:
    """无账户名时仍应明确 ID 的含义，空上下文不输出括号."""
    assert _context_label({"account_id": 1}) == "[账户#1] "
    assert _context_label({}) == ""


def test_console_format_uses_component_without_source_location() -> None:
    """控制台只显示业务组件，不显示模块、函数或行号."""
    record = _record(extra={"account_id": 1})
    template = _format_record(record)  # type: ignore[arg-type]

    assert record["extra"]["_component"] == "订单"  # type: ignore[index]
    assert record["extra"]["_ctx"] == "[账户#1] "  # type: ignore[index]
    assert "{extra[_component]}" in template
    assert "{name}" not in template
    assert "{function}" not in template
    assert "{line}" not in template


def test_json_format_emits_stable_unicode_schema() -> None:
    """文件 formatter 应生成一行可解析、保留中文与完整定位信息的 JSON."""
    record = _record(
        extra={
            "account_id": 1,
            "account_name": "测试网",
            "channel": "ctp",
            "execution_id": "0e7a80e92bc94d38",
            "symbol": "CF2701",
            "api_secret": "must-not-leak",
        }
    )
    template = _json_format_record(record)  # type: ignore[arg-type]
    payload = json.loads(record["extra"]["_json"])  # type: ignore[index]

    assert template == "{extra[_json]}\n"
    assert payload["schema_version"] == 1
    assert payload["timestamp"] == "2026-08-25T13:50:53.146+08:00"
    assert payload["component"] == "订单"
    assert payload["message"] == "定时查询完成: pending=1"
    assert payload["context"]["execution_id"] == "0e7a80e92bc94d38"
    assert payload["source"] == {
        "name": "axile.executor.algorithms.utils.order_tracker",
        "file": "/workspace/order_tracker.py",
        "function": "_query_pending_orders",
        "line": 571,
    }
    assert "api_secret" not in payload["context"]


def test_json_format_serializes_exception_traceback() -> None:
    """异常 JSON 应包含类型、消息与 traceback."""
    try:
        raise ValueError("测试异常")
    except ValueError as exc:
        exception = SimpleNamespace(type=type(exc), value=exc, traceback=exc.__traceback__)

    record = _record(exception=exception)
    _json_format_record(record)  # type: ignore[arg-type]
    payload = json.loads(record["extra"]["_json"])  # type: ignore[index]

    assert payload["exception"]["type"] == "ValueError"
    assert payload["exception"]["message"] == "测试异常"
    assert "ValueError: 测试异常" in payload["exception"]["traceback"]


def test_setup_logging_writes_versioned_jsonl_sink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """服务启动应停止创建文本日志，并配置 UTF-8 JSONL sink."""

    class _Logger:
        added: list[tuple[object, dict[str, object]]]

        def __init__(self) -> None:
            self.added = []

        def configure(self, **kwargs: object) -> None:
            _ = kwargs

        def info(self, message: object) -> None:
            _ = message

        def add(self, sink: object, **kwargs: object) -> None:
            self.added.append((sink, kwargs))

    fake_logger = _Logger()
    monkeypatch.setattr(log_config, "logger", fake_logger)
    monkeypatch.setattr(log_config, "setup_loguru_logging_intercept", lambda: None)
    monkeypatch.setattr(log_config.settings, "app_log_dir", tmp_path)
    monkeypatch.setattr(log_config.settings, "axile_log_rotation", "1 day")
    monkeypatch.setattr(log_config.settings, "environment", "local")

    log_config.setup_logging()

    assert len(fake_logger.added) == 1
    sink, options = fake_logger.added[0]
    assert sink == tmp_path / "axile.jsonl"
    assert options["format"] is log_config._json_format_record
    assert options["rotation"] == "1 day"
    assert options["encoding"] == "utf-8"
    assert not (tmp_path / "axile.log").exists()

"""``axile.server.core.log_config`` 中日志格式与上下文助手的单元测试."""

from axile.common.trade_channel import TradeChannel
from axile.server.core.log_config import (
    _context_label,
    _format_record,
    _short_name,
    execution_log_context,
)


def test_execution_log_context_expands_channel_enum() -> None:
    """``TradeChannel`` 应被展开为 ``.value`` 字符串，其余字段原样透传."""
    ctx = execution_log_context(
        account_id=1,
        account_name="测试网",
        channel=TradeChannel.CTP,
        execution_id="abc123",
    )
    assert ctx == {
        "account_id": 1,
        "account_name": "测试网",
        "channel": TradeChannel.CTP.value,
        "execution_id": "abc123",
    }


def test_execution_log_context_accepts_plain_channel_string() -> None:
    """非枚举渠道值应原样保留，不做转换."""
    ctx = execution_log_context(channel="ctp")
    assert ctx["channel"] == "ctp"


def test_execution_log_context_defaults_to_none() -> None:
    """未提供的字段应为 ``None``，便于上下文渲染时跳过."""
    ctx = execution_log_context()
    assert ctx == {
        "account_id": None,
        "account_name": None,
        "channel": None,
        "execution_id": None,
    }


def test_short_name_keeps_last_two_segments() -> None:
    """全限定 logger 名应收窄为末两段，去掉 ``axile.`` 前缀."""
    assert _short_name("axile.server.execution.backend") == "execution.backend"


def test_short_name_returns_short_name_unchanged() -> None:
    """段数不超过两段的短名应原样返回."""
    assert _short_name("__main__") == "__main__"


def test_short_name_truncates_overlong_tail_with_ellipsis() -> None:
    """超宽末段应以省略号前缀截断到固定宽度."""
    name = "provider_client.websocket_streams.websocket_streams"
    result = _short_name(name)
    assert len(result) == 22
    assert result.startswith("…")
    assert result.endswith("websocket_streams")


def test_short_name_returns_placeholder_when_name_is_none() -> None:
    """动态执行脚本时 ``record['name']`` 可能为 ``None``，应兜底为占位符而非崩溃."""
    assert _short_name(None) == "<unknown>"


def test_short_name_returns_placeholder_when_name_is_empty() -> None:
    """空字符串同样应兜底为占位符，避免 ``split`` 产出无意义结果."""
    assert _short_name("") == "<unknown>"


def test_context_label_renders_full_context() -> None:
    """完整上下文应渲染为紧凑前缀，execution_id 截断为前 8 位."""
    label = _context_label(
        {
            "account_id": 1,
            "account_name": "测试网",
            "channel": "ctp",
            "execution_id": "0e7a80e92bc94d38",
        }
    )
    assert label == "[1 测试网 ctp 0e7a80e9] "


def test_context_label_renders_partial_context() -> None:
    """仅有账户 ID 时应只渲染该字段."""
    assert _context_label({"account_id": 1}) == "[1] "


def test_context_label_empty_when_no_context() -> None:
    """无任何上下文字段时应返回空串，不产生多余方括号."""
    assert _context_label({}) == ""


def test_format_record_populates_aligned_fields() -> None:
    """格式函数应写入定宽的 level/name 字段并返回含 message 的模板."""

    class _Level:
        name = "WARNING"

    record = {
        "level": _Level(),
        "name": "axile.server.execution.backend",
        "extra": {"account_id": 1},
    }
    template = _format_record(record)  # type: ignore[arg-type]

    assert record["extra"]["_lvl"] == "WARN "
    assert record["extra"]["_name"] == f"{'execution.backend':<22}"
    assert record["extra"]["_ctx"] == "[1] "
    assert "{message}" in template
    assert "{extra[_ctx]}" in template


def test_format_record_falls_back_to_module_when_name_is_none() -> None:
    """``name`` 为 ``None`` 时应回退到 ``module``，模拟动态执行脚本的现场."""

    class _Level:
        name = "INFO"

    record = {
        "level": _Level(),
        "name": None,
        "module": "<string>",
        "extra": {},
    }
    _format_record(record)  # type: ignore[arg-type]

    assert record["extra"]["_name"] == f"{'<string>':<22}"


def test_format_record_handles_none_name_and_module() -> None:
    """``name`` 与 ``module`` 均缺失时应兜底为占位符，日志 handler 不得崩溃."""

    class _Level:
        name = "INFO"

    record = {
        "level": _Level(),
        "name": None,
        "extra": {},
    }
    _format_record(record)  # type: ignore[arg-type]

    assert record["extra"]["_name"] == f"{'<unknown>':<22}"

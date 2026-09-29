"""自定义通知函数的运行边界。"""

from axile.common.notification_config import validate_notification_config
from axile.common.notification_function import run_notification_function


def test_notification_function_runs_with_context() -> None:
    """同步函数可以读取事件快照，且不依赖飞书 webhook。"""
    result = run_notification_function(
        'def notify(context):\n    assert context["execution"]["id"] == "run-1"',
        {"execution": {"id": "run-1"}},
    )
    assert result.ok is True


def test_notification_function_accepts_public_context_annotation() -> None:
    """编辑器提供的类型标注在隔离通知进程中也可导入。"""
    code = (
        "from axile.common.notification_context import AccountNotificationContext\n"
        "def notify(context: AccountNotificationContext) -> None:\n"
        '    assert context["execution"]["is_test"]\n'
    )
    result = run_notification_function(code, {"execution": {"is_test": True}})
    assert result.ok is True


def test_notification_function_reports_source_line() -> None:
    """用户函数异常返回源码行号，不影响父进程。"""
    result = run_notification_function('def notify(context):\n    raise RuntimeError("boom")', {})
    assert result.ok is False
    assert result.error_line == 2
    assert "boom" in str(result.error)


def test_notification_function_rejects_keyword_only_or_async_entry() -> None:
    """编辑器与运行时都要求同步且可按位置传入上下文。"""
    for code in ("def notify(*, context):\n    pass", "async def notify(context):\n    pass"):
        result = run_notification_function(code, {})
        assert result.ok is False


def test_notification_config_requires_function_only_in_function_mode() -> None:
    """默认模式允许空源码；函数模式要求 notify 入口。"""
    validate_notification_config("default", None)
    try:
        validate_notification_config("function", "value = 1")
    except ValueError as exc:
        assert "notify(context)" in str(exc)
    else:
        raise AssertionError("缺少 notify 函数应被拒绝")

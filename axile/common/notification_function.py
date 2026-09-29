"""在独立进程中运行用户自定义通知函数。"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass

from axile.common.function_contract import accepts_context

NOTIFICATION_FUNCTION_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class NotificationFunctionResult:
    """单次通知函数运行结果。"""

    ok: bool
    error: str | None = None
    error_line: int | None = None


def validate_notification_function(code: str) -> None:
    """校验通知源码定义了 ``notify(context)``。"""
    if not code.strip():
        raise ValueError("通知函数不能为空")
    try:
        tree = ast.parse(code, filename="<notification>")
    except SyntaxError as exc:
        raise ValueError(f"第 {exc.lineno} 行语法错误: {exc.msg}") from exc
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "notify"
    ]
    if not functions:
        raise ValueError("脚本必须定义 notify(context) 函数")
    if isinstance(functions[-1], ast.AsyncFunctionDef):
        raise ValueError("notify 必须是同步函数")
    parameters = functions[-1].args
    if (
        len(parameters.posonlyargs) + len(parameters.args) != 1
        or parameters.vararg
        or parameters.kwarg
        or parameters.kwonlyargs
    ):
        raise ValueError("notify 必须且只能接收一个 context 参数")


def run_notification_function(
    code: str, context: dict[str, object], *, feishu_key: str | None = None
) -> NotificationFunctionResult:
    """运行通知函数并强制限制墙钟时间。"""
    try:
        validate_notification_function(code)
        process = subprocess.run(
            [sys.executable, "-m", "axile.common.notification_function", "--child"],
            input=json.dumps({"code": code, "context": context}, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=NOTIFICATION_FUNCTION_TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "AXILE_ACCOUNT_FEISHU_KEY": feishu_key or ""},
        )
        response = json.loads(process.stdout)
        return NotificationFunctionResult(
            ok=bool(response.get("ok")),
            error=str(response.get("error"))[:1000] if response.get("error") else None,
            error_line=response.get("error_line") if isinstance(response.get("error_line"), int) else None,
        )
    except subprocess.TimeoutExpired:
        return NotificationFunctionResult(False, f"通知函数执行超时（{NOTIFICATION_FUNCTION_TIMEOUT_SECONDS} 秒）")
    except (SyntaxError, ValueError) as exc:
        return NotificationFunctionResult(False, str(exc), getattr(exc, "lineno", None))
    except (OSError, json.JSONDecodeError) as exc:
        return NotificationFunctionResult(False, f"通知函数进程失败: {exc}")


def _run_child() -> None:
    """从标准输入读取事件，在子进程内执行用户函数。"""
    import contextlib
    import inspect
    import traceback

    try:
        request = json.load(sys.stdin)
        namespace: dict[str, object] = {}
        with contextlib.redirect_stdout(sys.stderr):
            exec(compile(request["code"], "<notification>", "exec"), namespace)  # noqa: S102
            function = namespace["notify"]
            if not callable(function) or not accepts_context(function):
                raise TypeError("notify 必须是同步函数，且只能接收一个位置参数 context")
            result = function(request["context"])
            if inspect.isawaitable(result):
                raise TypeError("notify 必须是同步函数")
        payload: dict[str, object] = {"ok": True}
    except BaseException as exc:  # noqa: BLE001 - 子进程边界将用户错误返回给父进程
        line = next(
            (
                frame.lineno
                for frame in reversed(traceback.extract_tb(exc.__traceback__))
                if frame.filename == "<notification>"
            ),
            None,
        )
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "error_line": line}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--child":
    _run_child()

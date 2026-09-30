"""用户提供的单参数函数调用契约。"""

from __future__ import annotations

import ast
import inspect


def accepts_context(function: object, *, allow_async: bool = False) -> bool:
    """判断函数能否按一个位置参数调用。

    Parameters
    ----------
    function : object
        待检查的入口。
    allow_async : bool, default=False
        通知可显式接受异步入口；组合函数保留同步契约。

    Returns
    -------
    bool
        入口是否满足调用契约。
    """
    if not callable(function) or (not allow_async and inspect.iscoroutinefunction(function)):
        return False
    try:
        signature = inspect.signature(function)
        signature.bind(object())
    except (TypeError, ValueError):
        return False
    return len(signature.parameters) == 1


def has_generator_yield(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """检查入口自身的 yield，排除内部函数、lambda 和类的作用域。"""
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return False

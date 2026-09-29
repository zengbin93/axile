"""用户提供的单参数同步函数调用契约。"""

from __future__ import annotations

import inspect


def accepts_context(function: object) -> bool:
    """判断函数能否按一个位置参数调用。"""
    if not callable(function) or inspect.iscoroutinefunction(function):
        return False
    try:
        signature = inspect.signature(function)
        signature.bind(object())
    except (TypeError, ValueError):
        return False
    return len(signature.parameters) == 1

"""执行过程共享的异常类型。"""

from __future__ import annotations


class ExecutionBlockedError(RuntimeError):
    """表示当前品种被执行前置条件拒绝，但不应视为算法失败。"""

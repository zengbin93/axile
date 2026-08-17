"""统一交易执行器抽象模块.

对外只暴露 `AbstractExecutor` 这一公开入口；
内部实现按 execution 聚合入口、runtime facade、生命周期、capability、facade、support 分文件组织。
"""

from axile.executor.abstract_executor.base import AbstractExecutor

__all__ = ["AbstractExecutor"]

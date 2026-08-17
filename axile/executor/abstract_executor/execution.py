"""`AbstractExecutor` 的 execution 侧聚合入口.

主文件只保留对外可见的 mixin 名称；具体实现按
runtime facade 与 execute 生命周期拆分到专用模块。
"""

from axile.executor.abstract_executor.execution_lifecycle import AbstractExecutorExecutionLifecycleMixin


class AbstractExecutorExecutionMixin(AbstractExecutorExecutionLifecycleMixin):
    """
    聚合 `AbstractExecutor` 的 execution 侧默认实现.

    Notes
    -----
    具体能力分别由以下模块承载：

    - `execution_runtime_facade.py`：execution runtime facade 聚合入口
    - `execution_runtime_host.py`：runtime 宿主、binding 与 query runtime 访问
    - `execution_runtime_audit.py`：审计上下文与事件/附件写入
    - `execution_runtime_account_control.py`：guard 绑定与记录导出
    - `execution_runtime_termination.py`：协作式终止状态读取与绑定
    - `execution_lifecycle.py`：`execute()` 主流程与 execution 内部共享查询
    """


__all__ = ["AbstractExecutorExecutionMixin"]

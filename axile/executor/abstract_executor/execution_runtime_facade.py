"""`AbstractExecutor` 的 execution runtime facade 聚合入口.

本模块只保留组合关系；具体实现按 runtime host、audit、
account control、termination 四个职责拆分到独立模块。
"""

from axile.executor.abstract_executor.execution_runtime_account_control import (
    AbstractExecutorExecutionAccountControlFacadeMixin,
)
from axile.executor.abstract_executor.execution_runtime_audit import (
    AbstractExecutorExecutionAuditFacadeMixin,
)
from axile.executor.abstract_executor.execution_runtime_host import (
    AbstractExecutorExecutionRuntimeHostMixin,
    _executor,
)
from axile.executor.abstract_executor.execution_runtime_termination import (
    AbstractExecutorExecutionTerminationFacadeMixin,
)


class AbstractExecutorExecutionRuntimeFacadeMixin(
    AbstractExecutorExecutionRuntimeHostMixin,
    AbstractExecutorExecutionAuditFacadeMixin,
    AbstractExecutorExecutionAccountControlFacadeMixin,
    AbstractExecutorExecutionTerminationFacadeMixin,
):
    """
    聚合 execution runtime 相关 facade 的组合 mixin。

    Notes
    -----
    具体实现已按职责拆分：

    - host：runtime 宿主与 query runtime 访问
    - audit：审计上下文与事件/附件写入
    - account control：guard 绑定与记录导出
    - termination：协作式终止状态读取与绑定
    """


__all__ = ["AbstractExecutorExecutionRuntimeFacadeMixin", "_executor"]

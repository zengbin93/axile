"""`AbstractExecutor` 的 execution runtime 协作式终止 facade."""

from __future__ import annotations

from axile.executor.abstract_executor.execution_runtime_host import _executor
from axile.executor.termination import ExecutionTerminationController


class AbstractExecutorExecutionTerminationFacadeMixin:
    """
    承载 execution runtime 的终止控制相关 facade。

    Notes
    -----
    该 mixin 只处理 terminate controller 的绑定与状态读取。
    """

    def set_termination_controller(self, controller: ExecutionTerminationController | None) -> None:
        """
        设置本次执行的协作式终止控制器。

        Parameters
        ----------
        controller : ExecutionTerminationController | None
            协作式终止控制器；传入 ``None`` 表示清空当前控制器。
        """
        _executor(self)._update_runtime_binding("termination_controller", controller)

    def is_termination_requested(self) -> bool:
        """
        判断当前 execution 是否已收到 terminate 请求。

        Returns
        -------
        bool
            已收到终止请求时返回 ``True``。
        """
        executor = _executor(self)
        runtime = executor.get_active_execution_runtime()
        if runtime is not None:
            # 执行态优先读 runtime，保证看到的是当前请求内最新的 terminate 视图。
            return runtime.is_termination_requested()
        executor._ensure_runtime_host()
        controller = executor._runtime_bindings.termination_controller
        if controller is None:
            return False
        # 还没建 runtime 时，binding 上的 controller 负责支撑预执行阶段的 terminate 判定。
        return controller.is_requested()

    def get_termination_mode(self) -> str | None:
        """
        读取当前 terminate 模式。

        Returns
        -------
        str | None
            当前终止模式；若未设置则返回 ``None``。
        """
        executor = _executor(self)
        runtime = executor.get_active_execution_runtime()
        if runtime is not None:
            return runtime.get_termination_mode()
        executor._ensure_runtime_host()
        controller = executor._runtime_bindings.termination_controller
        if controller is None:
            return None
        return controller.mode()

    def _get_termination_reason(self) -> str | None:
        """读取当前 terminate 原因。"""
        executor = _executor(self)
        runtime = executor.get_active_execution_runtime()
        if runtime is not None:
            return runtime.get_termination_reason()
        executor._ensure_runtime_host()
        controller = executor._runtime_bindings.termination_controller
        if controller is None:
            return None
        return controller.reason()

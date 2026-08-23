"""自定义组合脚本的子进程沙箱.

把用户上传的组合权重脚本从服务进程内 ``exec`` 挪进独立、短生命周期的子进程，
并施加 wall-time / CPU / 地址空间上限，避免脚本死循环或巨量分配拖垮承载实盘
交易的服务进程。
"""

from axile.server.sandbox.context_snapshot import (
    CONTEXT_SCALAR_PROPERTIES,
    ContextSnapshot,
    SnapshotContext,
    snapshot_context,
)
from axile.server.sandbox.script_runner import (
    DEFAULT_CPU_SECONDS,
    DEFAULT_MEMORY_MB,
    DEFAULT_WALL_TIMEOUT_SECONDS,
    CalendarScriptResult,
    ScriptExecutionError,
    ScriptResult,
    run_calendar_script,
    run_portfolio_script,
)

__all__ = [
    "CONTEXT_SCALAR_PROPERTIES",
    "DEFAULT_CPU_SECONDS",
    "DEFAULT_MEMORY_MB",
    "DEFAULT_WALL_TIMEOUT_SECONDS",
    "CalendarScriptResult",
    "ContextSnapshot",
    "ScriptExecutionError",
    "ScriptResult",
    "run_calendar_script",
    "SnapshotContext",
    "run_portfolio_script",
    "snapshot_context",
]

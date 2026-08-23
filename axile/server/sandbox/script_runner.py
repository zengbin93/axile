"""
自定义组合脚本的子进程沙箱执行器.

用户上传的组合权重脚本此前直接在服务进程内 ``exec``，只用 ``asyncio.to_thread``
挪到线程池——而 CPython 无法强杀线程，脚本里的 ``while True`` 无法通过取消协程
终止，巨量分配可直接 OOM 整个服务进程；调仓路径还会在持有账户执行锁的同时跑它，
把该账户的执行槽一并锁死。而这个进程同时承载实盘交易。

本模块把脚本挪进**独立、短生命周期的子进程**执行，并施加 wall-time / CPU /
地址空间上限，超时直接杀进程而非依赖协程取消。

Notes
-----
**不复用** ``axile.server.execution.worker_backend``：那套 worker 是「一账户一常驻
进程」，由声明 PROCESS backend 的渠道使用，且可能焐着实盘登录会话；把用户脚本塞进去等于把刚移除的爆炸
半径再装回来。用户脚本需要的恰恰是「一次一进程、跑完即弃」。

**不做 AST/import 白名单**（issue 里的可选项 4）：用户脚本可能需要发起网络请求并
使用 ``logger``，白名单会直接打断既有脚本。资源上限与进程隔离已经覆盖了「脚本把服务搞挂」这个
主要风险，而白名单要在不破坏既有用法的前提下做对，是独立议题。
"""

from __future__ import annotations

import multiprocessing
import sys
import traceback
from dataclasses import dataclass
from datetime import date
from multiprocessing.connection import Connection
from typing import Any, cast

from axile.server.sandbox.context_snapshot import ContextSnapshot, SnapshotContext

__all__ = [
    "DEFAULT_CPU_SECONDS",
    "DEFAULT_MEMORY_MB",
    "DEFAULT_WALL_TIMEOUT_SECONDS",
    "ScriptExecutionError",
    "CalendarScriptResult",
    "ScriptResult",
    "run_calendar_script",
    "run_portfolio_script",
]

DEFAULT_WALL_TIMEOUT_SECONDS = 300.0
"""脚本墙钟超时（秒）.

刻意给得宽松：仓库自带示例脚本会先发网络请求拉取持仓数据再用 pandas 计算，
网络等待不消耗 CPU 但会消耗墙钟时间。把一次合法的调仓因超时打断，比本 issue
要防的问题更糟，因此宁可靠 CPU 上限去快速捕捉死循环。
"""

DEFAULT_CPU_SECONDS = 60
"""脚本 CPU 时间上限（秒）.

死循环烧的是 CPU 而非墙钟，因此这道限制可以比墙钟紧得多，用于快速终结
``while True``；正常脚本的网络等待不计入 CPU 时间，不受影响。
"""

DEFAULT_MEMORY_MB = 2048
"""脚本地址空间上限（MB）.

``RLIMIT_AS`` 限制的是虚拟地址空间而非 RSS，而 pandas/numpy 会预留较大映射，
因此该值需明显高于脚本的实际内存占用，否则正常的 ``import pandas`` 就会失败。
"""


class ScriptExecutionError(ValueError):
    """
    自定义组合脚本执行失败.

    Notes
    -----
    继承 ``ValueError`` 而非 ``RuntimeError``：脚本签名/定义类错误在改为子进程执行
    之前就是以 ``ValueError`` 抛出的，调用方（含既有测试）按 ``ValueError`` 捕获。
    保持这一基类可以让沙箱改造对上层调用契约完全透明。

    Attributes
    ----------
    error_line : int | None
        用户脚本中的出错行号；无法定位时为 ``None``。
    error_offset : int | None
        用户脚本中的出错列偏移；仅语法错误可得。
    error_type : str
        原始异常类型名。
    error_message : str
        简洁错误消息。
    formatted_traceback : str
        子进程侧格式化好的完整 traceback。
    """

    def __init__(
        self,
        message: str,
        *,
        error_line: int | None = None,
        error_offset: int | None = None,
        error_type: str = "RuntimeError",
        error_message: str = "",
        formatted_traceback: str = "",
    ) -> None:
        """初始化脚本执行错误."""
        super().__init__(message)
        self.error_line = error_line
        self.error_offset = error_offset
        self.error_type = error_type
        self.error_message = error_message or message
        self.formatted_traceback = formatted_traceback


@dataclass(slots=True)
class ScriptResult:
    """
    脚本执行结果.

    Attributes
    ----------
    ok : bool
        是否成功。
    target : dict[str, float] | None
        成功时脚本返回的目标权重。
    error : ScriptExecutionError | None
        失败时的结构化错误。
    """

    ok: bool
    target: dict[str, float] | None = None
    error: ScriptExecutionError | None = None


@dataclass(slots=True)
class CalendarScriptResult:
    """自定义交易日历脚本的通用结果。"""

    ok: bool
    value: Any = None
    error: ScriptExecutionError | None = None


def _extract_error_fields(exc: BaseException) -> tuple[int | None, int | None, str, str]:
    """
    从异常中提取用户代码出错位置与简洁消息.

    Parameters
    ----------
    exc : BaseException
        脚本执行过程中捕获到的异常。

    Returns
    -------
    tuple[int | None, int | None, str, str]
        ``(行号, 列偏移, 异常类型名, 简洁消息)``；无法定位时行号/列偏移为 ``None``。

    Notes
    -----
    该提取**必须在子进程内完成**：异常对象与其 traceback 无法跨进程传递，若只把
    ``str(exc)`` 送回主进程，校验接口的 ``error_line`` / ``error_offset`` 就会静默
    退化成 ``None``。逻辑与主进程原先的 ``_extract_user_code_error`` 一致——用户
    脚本经 ``exec(code, ...)`` 编译，代码对象文件名为 ``<string>``，据此把出错行
    定位回用户粘贴的代码，忽略内部调用栈。
    """
    error_type = type(exc).__name__
    if isinstance(exc, SyntaxError):
        return exc.lineno, exc.offset, error_type, exc.msg or str(exc)

    line: int | None = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == "<string>":
            line = frame.lineno
    return line, None, error_type, str(exc)


def _darwin_virtual_size_bytes() -> int:
    """
    读取 Darwin 当前进程的虚拟地址空间大小.

    Returns
    -------
    int
        当前进程已映射的虚拟地址空间字节数。

    Raises
    ------
    OSError
        Mach ``task_info`` 调用失败时抛出。

    Notes
    -----
    Darwin 会为进程映射数百 GiB 的共享虚拟区域，远大于实际常驻内存。直接把
    ``RLIMIT_AS`` 设成脚本预算会因低于当前虚拟地址空间而被内核拒绝，因此需要先
    读取启动基线，再把脚本预算追加到基线上。
    """
    import ctypes

    mach_task_basic_info = 20
    info_word_count = 12
    info = (ctypes.c_uint64 * (info_word_count // 2))()
    info_count = ctypes.c_uint(info_word_count)

    library = ctypes.CDLL(None)
    mach_task_self = library.mach_task_self
    mach_task_self.restype = ctypes.c_uint
    task_info = library.task_info
    task_info.argtypes = [
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    task_info.restype = ctypes.c_int

    result = task_info(
        mach_task_self(),
        mach_task_basic_info,
        ctypes.byref(info),
        ctypes.byref(info_count),
    )
    if result != 0:
        raise OSError(f"读取 Darwin 进程虚拟地址空间失败（kern_return={result}）")
    return int(info[0])


def _address_space_limit_bytes(memory_mb: int) -> int:
    """
    计算当前平台应设置的地址空间上限.

    Parameters
    ----------
    memory_mb : int
        允许脚本使用的内存预算（MB）。

    Returns
    -------
    int
        传给 ``RLIMIT_AS`` 的字节数。

    Notes
    -----
    Linux 的 ``RLIMIT_AS`` 使用进程总地址空间，沿用绝对上限。Darwin 的进程启动
    基线包含巨大的系统共享映射，需在基线上追加预算，才能既成功设置限制，又约束
    脚本后续分配。
    """
    budget_bytes = memory_mb * 1024 * 1024
    if sys.platform == "darwin":
        return _darwin_virtual_size_bytes() + budget_bytes
    return budget_bytes


def _apply_windows_process_memory_limit(memory_mb: int) -> None:
    """用 Job Object 限制当前 Windows 子进程的提交内存。"""
    import ctypes
    from ctypes import wintypes

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())

    information = _JobObjectExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    information.ProcessMemoryLimit = memory_mb * 1024 * 1024
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(information), ctypes.sizeof(information)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    # 子进程短生命周期内保留 Job handle；进程退出时由内核统一回收。


def _apply_resource_limits(cpu_seconds: int, memory_mb: int) -> None:
    """
    在子进程内施加 CPU 与地址空间上限.

    Parameters
    ----------
    cpu_seconds : int
        CPU 时间上限（秒）。
    memory_mb : int
        地址空间上限（MB）。

    Notes
    -----
    POSIX 使用 ``resource``；Windows 使用 Job Object 限制进程提交内存。Windows
    没有对应的 CPU 秒数限制，仍由墙钟超时兜底。
    """
    if sys.platform == "win32":
        _apply_windows_process_memory_limit(memory_mb)
        return

    try:
        import resource
    except ImportError:  # pragma: no cover - 非主流平台降级
        return

    for limit_name, value in (
        ("RLIMIT_CPU", cpu_seconds),
        ("RLIMIT_AS", _address_space_limit_bytes(memory_mb)),
    ):
        limit = getattr(resource, limit_name, None)
        if limit is None:  # pragma: no cover - 平台差异
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (OSError, ValueError):  # pragma: no cover - 受宿主策略限制时跳过
            continue


def _child_entry(
    conn: Connection,
    code: str,
    snapshot: ContextSnapshot | None,
    cpu_seconds: int,
    memory_mb: int,
) -> None:
    """
    子进程入口：施加资源上限并执行用户脚本.

    Parameters
    ----------
    conn : Connection
        回传结果的管道端。
    code : str
        用户脚本源码。
    snapshot : ContextSnapshot | None
        账户上下文快照；``None`` 表示脚本不需要上下文。
    cpu_seconds : int
        CPU 时间上限（秒）。
    memory_mb : int
        地址空间上限（MB）。
    """
    _apply_resource_limits(cpu_seconds, memory_mb)

    context: object | None = None if snapshot is None else SnapshotContext(snapshot)
    try:
        target = _execute_user_code(code, context)
    except BaseException as exc:  # noqa: BLE001 - 沙箱需捕获一切脚本错误并结构化回传
        line, offset, error_type, message = _extract_error_fields(exc)
        payload = {
            "ok": False,
            "error_line": line,
            "error_offset": offset,
            "error_type": error_type,
            "error_message": message,
            "traceback": traceback.format_exc(),
        }
    else:
        payload = {"ok": True, "target": target}

    try:
        conn.send(payload)
    except (BrokenPipeError, OSError):  # pragma: no cover - 主进程已放弃等待
        pass
    finally:
        conn.close()


def _execute_user_code(code: str, context: object | None) -> dict[str, float]:
    """
    在当前（子）进程内执行用户脚本并取回目标权重.

    Parameters
    ----------
    code : str
        用户脚本源码。
    context : object | None
        传给 ``calculate_portfolio(context)`` 的上下文对象。

    Returns
    -------
    dict[str, float]
        脚本返回的目标权重。

    Raises
    ------
    ValueError
        脚本未定义 ``calculate_portfolio(context)`` 或签名不符时抛出。
    """
    import inspect

    namespace: dict[str, object] = {"Context": context}
    exec(code, namespace)  # noqa: S102 - 沙箱子进程内执行用户脚本即本模块职责

    calc_func = namespace.get("calculate_portfolio")
    if not callable(calc_func):
        raise ValueError("calculate_portfolio 函数未找到或不可调用")

    signature = inspect.signature(calc_func)
    if len(signature.parameters) != 1:
        raise ValueError("calculate_portfolio 必须定义为 calculate_portfolio(context)")

    return cast("dict[str, float]", calc_func(context))


def _execute_calendar_code(code: str, calendar_id: str, start: date, end: date) -> object:
    """执行交易日历函数并返回其原始结果。"""
    import inspect

    namespace: dict[str, object] = {"date": date}
    exec(code, namespace)  # noqa: S102 - 受限子进程内执行用户脚本
    function = namespace.get("get_trading_calendar")
    if not callable(function):
        raise ValueError("get_trading_calendar 函数未找到或不可调用")
    signature = inspect.signature(function)
    if len(signature.parameters) != 3:
        raise ValueError("get_trading_calendar 必须定义为 get_trading_calendar(calendar_id, start, end)")
    return function(calendar_id, start, end)


def _calendar_child_entry(
    conn: Connection,
    code: str,
    calendar_id: str,
    start: date,
    end: date,
    cpu_seconds: int,
    memory_mb: int,
) -> None:
    """在隔离子进程中执行交易日历函数。"""
    _apply_resource_limits(cpu_seconds, memory_mb)
    try:
        value = _execute_calendar_code(code, calendar_id, start, end)
    except BaseException as exc:  # noqa: BLE001 - 需把脚本错误结构化回传
        line, offset, error_type, message = _extract_error_fields(exc)
        payload = {
            "ok": False,
            "error_line": line,
            "error_offset": offset,
            "error_type": error_type,
            "error_message": message,
            "traceback": traceback.format_exc(),
        }
    else:
        payload = {"ok": True, "value": value}
    try:
        conn.send(payload)
    except (BrokenPipeError, OSError):
        pass
    finally:
        conn.close()


def _terminate(process: multiprocessing.process.BaseProcess) -> None:
    """
    强制终止子进程，先 terminate 再 kill，确保不留僵尸.

    Parameters
    ----------
    process : multiprocessing.process.BaseProcess
        待终止的子进程。
    """
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
    if process.is_alive():
        kill = getattr(process, "kill", None)
        if callable(kill):
            kill()
        process.join(timeout=2.0)
    # join 已回收退出状态；这里再兜一次，避免 terminate 后仍处于僵尸态。
    if not process.is_alive():
        process.join(timeout=0.1)


def run_portfolio_script(
    code: str,
    snapshot: ContextSnapshot | None = None,
    *,
    wall_timeout: float = DEFAULT_WALL_TIMEOUT_SECONDS,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_mb: int = DEFAULT_MEMORY_MB,
) -> ScriptResult:
    """
    在受限子进程中执行自定义组合脚本.

    Parameters
    ----------
    code : str
        用户脚本源码。
    snapshot : ContextSnapshot | None, optional
        账户上下文快照；``None`` 表示脚本不需要上下文。
    wall_timeout : float, optional
        墙钟超时（秒），超时后杀死子进程。
    cpu_seconds : int, optional
        CPU 时间上限（秒）。
    memory_mb : int, optional
        地址空间上限（MB）。

    Returns
    -------
    ScriptResult
        统一的执行结果；失败时 ``error`` 携带结构化错误信息。

    Notes
    -----
    返回中性结果对象而非直接抛异常：三个调用方各有不同的错误契约（HTTP 400 /
    结构化 ``valid=False`` / ``ValueError`` + 审计记录），由各自映射，避免沙箱
    实现细节泄漏进三套处理逻辑。

    子进程用 ``spawn`` 启动，不继承主进程的线程、锁与事件循环状态——``fork``
    在持有账户执行锁的调仓路径上复制锁状态会带来难以排查的问题。
    """
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_child_entry,
        args=(child_conn, code, snapshot, cpu_seconds, memory_mb),
        name="axile-portfolio-script",
        daemon=True,
    )
    process.start()
    child_conn.close()

    try:
        return _collect_result(parent_conn, process, wall_timeout, cpu_seconds, memory_mb)
    finally:
        _terminate(process)
        try:
            parent_conn.close()
        except OSError:  # pragma: no cover - 管道已关闭
            pass


def run_calendar_script(
    code: str,
    calendar_id: str,
    start: date,
    end: date,
    *,
    wall_timeout: float = DEFAULT_WALL_TIMEOUT_SECONDS,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_mb: int = DEFAULT_MEMORY_MB,
) -> CalendarScriptResult:
    """在公共脚本沙箱中执行自定义交易日历函数。"""
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_calendar_child_entry,
        args=(child_conn, code, calendar_id, start, end, cpu_seconds, memory_mb),
        name="axile-calendar-script",
        daemon=True,
    )
    process.start()
    child_conn.close()
    try:
        if not parent_conn.poll(wall_timeout):
            return CalendarScriptResult(
                ok=False,
                error=ScriptExecutionError(
                    f"自定义交易日历脚本执行超时（超过 {wall_timeout:.0f} 秒），已终止",
                    error_type="TimeoutError",
                ),
            )
        try:
            payload = cast("dict[str, object]", parent_conn.recv())
        except EOFError:
            process.join(timeout=1.0)
            return CalendarScriptResult(
                ok=False,
                error=ScriptExecutionError(
                    f"自定义交易日历脚本异常退出（exitcode={process.exitcode}）",
                    error_type="ResourceLimitExceeded",
                ),
            )
        if payload.get("ok"):
            return CalendarScriptResult(ok=True, value=payload.get("value"))
        error_type = cast(str, payload.get("error_type") or "RuntimeError")
        message = cast(str, payload.get("error_message") or "") or error_type
        return CalendarScriptResult(
            ok=False,
            error=ScriptExecutionError(
                message,
                error_line=cast("int | None", payload.get("error_line")),
                error_offset=cast("int | None", payload.get("error_offset")),
                error_type=error_type,
                error_message=message,
                formatted_traceback=cast(str, payload.get("traceback") or ""),
            ),
        )
    finally:
        _terminate(process)
        parent_conn.close()


def _collect_result(
    parent_conn: Connection,
    process: multiprocessing.process.BaseProcess,
    wall_timeout: float,
    cpu_seconds: int,
    memory_mb: int,
) -> ScriptResult:
    """
    等待并解析子进程回传的执行结果.

    Parameters
    ----------
    parent_conn : Connection
        读取结果的管道端。
    process : multiprocessing.process.BaseProcess
        执行脚本的子进程。
    wall_timeout : float
        墙钟超时（秒）。
    cpu_seconds : int
        CPU 时间上限（秒），用于组织超时提示。
    memory_mb : int
        地址空间上限（MB），用于组织异常退出提示。

    Returns
    -------
    ScriptResult
        统一的执行结果。
    """
    if not parent_conn.poll(wall_timeout):
        return _failure(
            f"自定义组合脚本执行超时（超过 {wall_timeout:.0f} 秒），已终止",
            error_type="TimeoutError",
        )

    try:
        payload = cast("dict[str, object]", parent_conn.recv())
    except EOFError:
        # 子进程未回传结果即退出：最典型的是触发 RLIMIT_CPU（SIGXCPU）或被 OOM
        # killer 杀掉，此时管道会 EOF 而非收到 payload。
        process.join(timeout=1.0)
        return _failure(
            f"自定义组合脚本异常退出（exitcode={process.exitcode}），"
            f"通常为超出 CPU 上限 {cpu_seconds}s 或内存上限 {memory_mb}MB",
            error_type="ResourceLimitExceeded",
        )

    if payload.get("ok"):
        return ScriptResult(ok=True, target=cast("dict[str, float]", payload.get("target")))

    # MemoryError 等异常的 str() 为空串，此时退回类型名，避免把「内存超限」显示成
    # 无信息的「执行失败」。
    error_type = cast(str, payload.get("error_type") or "RuntimeError")
    message = cast(str, payload.get("error_message") or "") or f"自定义组合脚本执行失败: {error_type}"
    return ScriptResult(
        ok=False,
        error=ScriptExecutionError(
            message,
            error_line=cast("int | None", payload.get("error_line")),
            error_offset=cast("int | None", payload.get("error_offset")),
            error_type=error_type,
            error_message=message,
            formatted_traceback=cast(str, payload.get("traceback") or ""),
        ),
    )


def _failure(message: str, *, error_type: str) -> ScriptResult:
    """
    构造一个沙箱层面的失败结果（非脚本自身抛出的异常）.

    Parameters
    ----------
    message : str
        错误描述。
    error_type : str
        错误类型名。

    Returns
    -------
    ScriptResult
        失败结果。
    """
    return ScriptResult(
        ok=False,
        error=ScriptExecutionError(
            message,
            error_type=error_type,
            error_message=message,
            formatted_traceback=message,
        ),
    )

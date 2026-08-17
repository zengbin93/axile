"""
单 worker 部署护栏.

Axile 的实盘互斥、定时调度与实时进度镜像**全部是进程内内存态**：

- 账户执行互斥锁是模块级 ``threading.Lock`` + 全局 dict
  （``axile.server.execution.registry``），只做线程级互斥；
- 定时调度器是 ``AsyncIOScheduler`` + ``MemoryJobStore``
  （``axile.server.core.scheduler``），无持久化、无 leader 选举；
- 实盘进度镜像与 SSE 订阅者是内存态单例 ``live_hub``
  （``axile.server.execution.live``）。

因此一旦以多 worker 部署，同一账户可在不同进程并发执行（互斥锁被完全旁路，
可能重复下单/重复撤单），且每个 worker 的 lifespan 都会各自
``init_scheduler()``，同一 cron 触发点会被触发 N 次。

在把上述三件内存态迁移到共享基础设施（DB running 标志 + 分布式锁、leader
选举、Redis pub/sub）之前，正确做法是**拒绝启动**而不是带病运行——多下一笔
单的代价远大于起不来。本模块提供该护栏，覆盖两条入口：

1. CLI（``axile.server.main``）：解析参数后立即校验 ``--workers``；
2. 任意外部启动方式（``uvicorn --workers N`` / ``gunicorn -w N``）：在
   FastAPI lifespan 里回溯调用栈上的 ``uvicorn.Config``，读取其 ``workers``。

Notes
-----
第 2 条之所以可靠：uvicorn 多 worker 时由 ``Multiprocess`` supervisor 把
``Config``（含 ``workers=N``）传给每个子进程，子进程在 ``subprocess_started``
帧中持有它，故 lifespan 能在栈上看到真实的 ``workers`` 值。而 ``--reload``
同样会 spawn 子进程，但其 ``Config.workers`` 恒为 1，因此本护栏不会误伤
开发模式的热重载。
"""

from __future__ import annotations

import inspect
import os

__all__ = [
    "MultiWorkerNotSupportedError",
    "detect_configured_workers",
    "ensure_single_worker",
    "validate_workers_option",
]

_MULTI_WORKER_HINT = (
    "axile 暂不支持多 worker 部署：账户执行互斥锁、定时调度器与实盘进度镜像均为进程内内存态，"
    "多进程下互斥失效，可能重复调度与重复下单，同一 cron 触发点也会被触发多次。"
    "请以单 worker 启动（省略 --workers，或显式 --workers 1）。"
)


class MultiWorkerNotSupportedError(RuntimeError):
    """检测到多 worker 部署时抛出的异常."""


def _gunicorn_worker_count() -> int | None:
    """
    从 gunicorn 注入的环境变量推断 worker 数.

    Returns
    -------
    int | None
        解析成功时返回 worker 数；非 gunicorn 环境或无法解析时返回 ``None``。

    Notes
    -----
    gunicorn 在 master 进程中通过 ``GUNICORN_CMD_ARGS`` 或 ``WEB_CONCURRENCY``
    传递并发度；两者都是约定俗成的部署入口，这里做尽力而为的解析，解析失败
    不阻断启动（真正的兜底仍是 uvicorn ``Config`` 回溯）。
    """
    raw = os.environ.get("WEB_CONCURRENCY")
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def detect_configured_workers() -> int | None:
    """
    探测当前进程被配置的 worker 数.

    Returns
    -------
    int | None
        探测到的 worker 数；无法确定时返回 ``None``。

    Notes
    -----
    优先回溯调用栈上的 ``uvicorn.Config``：多 worker 时 supervisor 会把该
    配置对象传入每个子进程，因此这是最直接可信的来源。回溯不到时退化为读取
    ``WEB_CONCURRENCY`` 环境变量（gunicorn 常用约定）。

    该函数只做探测、不抛异常，便于调用方决定告警还是拒绝启动。
    """
    for frame_info in inspect.stack():
        config = frame_info.frame.f_locals.get("config")
        if config is None or type(config).__name__ != "Config":
            continue
        workers = getattr(config, "workers", None)
        if isinstance(workers, int):
            return workers

    return _gunicorn_worker_count()


def validate_workers_option(workers: int | None) -> None:
    """
    校验 CLI ``--workers`` 取值，拒绝多 worker.

    Parameters
    ----------
    workers : int | None
        CLI 传入的 worker 数；``None`` 表示未显式指定。

    Raises
    ------
    MultiWorkerNotSupportedError
        当 ``workers`` 大于 1 时抛出。

    Notes
    -----
    ``workers <= 0`` 视为非法输入，同样拒绝——静默当成 1 会让运维以为参数生效了。
    """
    if workers is None:
        return

    if workers < 1:
        raise MultiWorkerNotSupportedError(f"--workers 必须为正整数，收到 {workers}。")

    if workers > 1:
        raise MultiWorkerNotSupportedError(f"--workers={workers} 不被支持。{_MULTI_WORKER_HINT}")


def ensure_single_worker() -> None:
    """
    在服务启动阶段确认当前为单 worker 部署，否则拒绝启动.

    Raises
    ------
    MultiWorkerNotSupportedError
        当探测到 worker 数大于 1 时抛出，阻止进程进入可交易状态。

    Notes
    -----
    该检查放在 FastAPI lifespan 中，因此对 ``uvicorn --workers N``、
    ``gunicorn -w N -k uvicorn.workers.UvicornWorker`` 等**绕过 CLI 的外部
    启动方式同样生效**。探测不到 worker 配置时按单 worker 放行：宁可漏判也
    不能让正常的单进程启动被误杀。
    """
    workers = detect_configured_workers()
    if workers is not None and workers > 1:
        raise MultiWorkerNotSupportedError(f"检测到以 {workers} 个 worker 启动。{_MULTI_WORKER_HINT}")

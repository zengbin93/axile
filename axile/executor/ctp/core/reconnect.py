"""
管理 CTP 客户端的通用重连线程与重试策略.

该模块把“何时开始重连”“多久重试一次”“成功后如何恢复现场”从具体
交易端和行情端实现里抽离出来，避免两套客户端分别维护近似但容易漂移的逻辑。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import loguru


@dataclass
class ReconnectPolicy:
    """
    描述 CTP 客户端的重连策略.

    Attributes
    ----------
    enable_auto_reconnect : bool
        是否在断连后自动启动重连线程。
    max_reconnect_attempts : int
        单轮重连允许的最大尝试次数。
    reconnect_interval : float
        固定重试模式下的基础等待时间，单位为秒。
    connection_timeout : float
        单次连接或登录等待超时时间，单位为秒。
    exponential_backoff : bool
        是否按指数退避放大重试间隔。
    max_reconnect_interval : float
        指数退避模式下的最大等待时间，单位为秒。
    heartbeat_interval : float
        心跳检查间隔，单位为秒；当前主要作为共享策略字段保留。
    enable_backup_servers : bool
        是否允许切换备用前置。
    backup_servers : list[str]
        备用前置地址列表。
    """

    enable_auto_reconnect: bool = True
    max_reconnect_attempts: int = 5
    reconnect_interval: float = 3.0
    connection_timeout: float = 30.0
    exponential_backoff: bool = False
    max_reconnect_interval: float = 30.0
    heartbeat_interval: float = 30.0
    enable_backup_servers: bool = False
    backup_servers: list[str] = field(default_factory=list)


class ReconnectController:
    """
    管理单个客户端的重连线程生命周期与恢复回调.

    Notes
    -----
    一个控制器在任意时刻只维护一个重连工作线程，避免同一连接同时被多个
    重连流程争抢，导致重复登录或重复恢复订阅。
    """

    def __init__(
        self,
        name: str,
        policy: ReconnectPolicy,
        attempt_reconnect: Callable[[], bool],
        on_reconnect_success: Callable[[], None] | None = None,
        logger: object | None = None,
    ) -> None:
        """
        初始化重连控制器.

        Parameters
        ----------
        name : str
            日志中展示的客户端名称。
        policy : ReconnectPolicy
            当前控制器使用的重连策略。
        attempt_reconnect : Callable[[], bool]
            执行单次重连动作的回调，成功时返回 ``True``。
        on_reconnect_success : Callable[[], None] | None, optional
            重连成功后执行的恢复回调，例如重新订阅或重新拉取状态。
        logger : object | None, optional
            日志对象；为 ``None`` 时使用 ``loguru.logger``。
        """
        self.name = name
        self.policy = policy
        self._attempt_reconnect = attempt_reconnect
        self._on_reconnect_success = on_reconnect_success
        self.logger = logger or loguru.logger

        self.attempts = 0
        self.last_disconnect_time = 0.0
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """返回重连工作线程是否仍在运行."""
        return self._thread is not None and self._thread.is_alive()

    def compute_interval(self, attempt_number: int) -> float:
        """计算下次重连尝试前的休眠间隔."""
        if not self.policy.exponential_backoff:
            return self.policy.reconnect_interval

        return min(
            self.policy.reconnect_interval * (2 ** max(attempt_number - 1, 0)),
            self.policy.max_reconnect_interval,
        )

    def notify_disconnect(self) -> None:
        """记录断连事件，并在启用时启动重连."""
        self.last_disconnect_time = time.time()
        if self.policy.enable_auto_reconnect:
            self.start()
        else:
            self.logger.warning(f"⚠️  {self.name}自动重连已禁用，需要手动重连")

    def start(self) -> None:
        """若重连工作线程尚未运行，则启动它."""
        with self._lock:
            # 启动逻辑必须串行化，否则多个断连事件可能同时拉起重复的重连线程。
            if self.is_running:
                return

            self.stop_event.clear()
            self._thread = threading.Thread(target=self._run, name=f"{self.name}-Reconnect-Thread", daemon=True)
            self._thread.start()
            self.logger.info(f"🔄 启动{self.name}自动重连线程")

    def _run(self) -> None:
        """重连工作线程循环."""
        self.attempts = 0
        while not self.stop_event.is_set() and self.attempts < self.policy.max_reconnect_attempts:
            try:
                self.attempts += 1
                interval = self.compute_interval(self.attempts)
                self.logger.warning(f"🔄 {self.name}第 {self.attempts} 次重连尝试，{interval:.1f}秒后开始...")

                if self.stop_event.wait(interval):
                    break

                if self._attempt_reconnect():
                    self.logger.info(f"✅ {self.name}第 {self.attempts} 次重连成功！")
                    self.attempts = 0
                    # 恢复回调只在连接真正恢复后执行，避免把旧会话状态误恢复到失败连接上。
                    if self._on_reconnect_success is not None:
                        self._on_reconnect_success()
                    return

                self.logger.error(f"❌ {self.name}第 {self.attempts} 次重连失败")
            except Exception as exc:
                self.logger.error(f"{self.name}重连过程中发生异常: {exc}")

        if self.attempts >= self.policy.max_reconnect_attempts:
            self.logger.error(f"💀 {self.name}重连失败！已尝试 {self.attempts} 次，放弃重连。")

        self.attempts = 0

    def stop(self, timeout: float = 5.0) -> None:
        """
        停止重连工作线程.

        Parameters
        ----------
        timeout : float, default=5.0
            等待工作线程退出的最长时间，单位为秒。
        """
        self.stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def join(self, timeout: float | None = None) -> None:
        """在重连工作线程存在时等待其结束."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def update_policy(self, **kwargs: object) -> tuple[dict[str, object], list[str]]:
        """
        更新已知策略字段，并返回变更项与未知字段.

        Returns
        -------
        tuple[dict[str, object], list[str]]
            第一个元素为已生效的字段更新，第二个元素为未识别字段名列表。
        """
        changed: dict[str, object] = {}
        unknown: list[str] = []
        for key, value in kwargs.items():
            if hasattr(self.policy, key):
                setattr(self.policy, key, value)
                changed[key] = value
            else:
                unknown.append(key)
        return changed, unknown

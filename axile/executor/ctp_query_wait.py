"""CTP 流式查询空闲计时，显式排除回调本地处理区间。"""

from __future__ import annotations

import threading
from collections.abc import Callable

from axile.executor.algorithms.utils.clock import clock_monotonic


class QueryIdleClock:
    """回调入口与超时判定共享一把锁，避免末条回调竞争。"""

    def __init__(self, clock: Callable[[], float] = clock_monotonic) -> None:
        self.clock = clock
        self.lock = threading.Lock()
        self.last = clock()
        self.processing = 0
        self.expired = False
        self.max_idle = 0.0
        self.processing_seconds = 0.0
        self.started = self.last

    def sent(self) -> None:
        """发送完成才开始等待，排除限流排队。"""
        with self.lock:
            # 同步 fake API 可能在发送函数返回前已调用回调。
            if not self.processing:
                self.last = self.clock()

    def enter(self, timeout: float | None = None) -> bool:
        """回调入口暂停网络计时，拒绝超时后的回调。"""
        with self.lock:
            if self.expired:
                return False
            now = self.clock()
            if not self.processing:
                if timeout is not None and now - self.last >= timeout:
                    self.expired = True
                    return False
                self.max_idle = max(self.max_idle, now - self.last)
                self.started = now
            self.processing += 1
            return True

    def leave(self) -> None:
        """本地处理结束后重新开始空闲计时。"""
        with self.lock:
            self.processing -= 1
            if not self.processing:
                self.last = self.clock()
                self.processing_seconds += self.last - self.started

    def timed_out(self, timeout: float, done: threading.Event) -> bool:
        """原子判断是否在无回调且无本地处理时超时。"""
        with self.lock:
            if done.is_set() or self.processing:
                return False
            if self.expired:
                return True
            self.expired = self.clock() - self.last >= timeout
            return self.expired

"""共享时钟在仿真时间下的时间戳与等待行为。"""

import asyncio

from axile.executor.algorithms.utils import clock as clock_module


class AdvancingClock:
    """等待时推进时间的轻量时钟。"""

    def __init__(self, timestamp: float) -> None:
        self.timestamp = timestamp

    def time(self) -> float:
        return self.timestamp

    def sleep(self, seconds: float) -> None:
        self.timestamp += seconds


def test_virtual_deadlines_and_waits_advance_without_wall_clock(monkeypatch) -> None:
    clock = AdvancingClock(1000)
    monkeypatch.setattr(clock_module, "_default_clock", clock)

    deadline = clock_module.clock_monotonic() + 5
    asyncio.run(clock_module.clock_async_sleep(5))

    assert clock_module.clock_monotonic() == deadline
    assert clock_module.clock_now_ms() == 1_005_000

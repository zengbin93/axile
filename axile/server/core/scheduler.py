"""Axile 服务端共用的 APScheduler 实例."""

from apscheduler.jobstores.memory import MemoryJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.asyncio import AsyncIOScheduler as Scheduler  # type: ignore[import-untyped]

scheduler = Scheduler(jobstores={"default": MemoryJobStore()}, timezone="Asia/Shanghai")

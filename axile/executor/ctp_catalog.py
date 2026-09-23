"""按柜台和交易日共享合约目录；不依赖服务端或 OpenCTP。"""

from __future__ import annotations

import pickle
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol
from uuid import uuid4

from axile.executor.algorithms.utils.clock import get_default_clock

CatalogKey = tuple[str, str, str]
CatalogRows = dict[str, dict[str, object]]


@dataclass(frozen=True)
class InstrumentRecord:
    """保留原生字段名称的只读合约快照。"""

    values: Mapping[str, object]

    def __getattr__(self, name: str) -> Any:
        """以原生字段名读取已脱离回调帧的值。"""
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def decode_catalog(data: bytes) -> Mapping[str, InstrumentRecord]:
    """解码本进程或受信任子进程生成的快照，不接受外部 pickle。"""
    rows: CatalogRows = pickle.loads(data)
    return MappingProxyType({key: InstrumentRecord(MappingProxyType(row)) for key, row in rows.items()})


@dataclass
class CatalogLoad:
    """加载代次；失败后等待者仍能观察这一代的失败。"""

    owner: str
    token: str = field(default_factory=lambda: uuid4().hex)
    data: bytes | None = None
    error: str | None = None
    progress: int = 0


class CatalogStore:
    """线程安全的单次加载协调器，缓存仅包含完整成功结果。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loads: dict[CatalogKey, CatalogLoad] = {}

    def acquire(self, key: CatalogKey, owner: str) -> CatalogLoad:
        """复用成功结果或在失败后创建新加载代次。"""
        with self._lock:
            load = self._loads.get(key)
            if load is None or load.error is not None:
                load = CatalogLoad(owner)
                self._loads[key] = load
            return load

    def inspect(self, load: CatalogLoad) -> tuple[bytes | None, str | None, int]:
        """读取同一代的结果、失败原因与进度。"""
        with self._lock:
            return load.data, load.error, load.progress

    def publish(self, key: CatalogKey, load: CatalogLoad, rows: CatalogRows) -> None:
        """只允许有效代次原子发布非空完整目录。"""
        if not rows:
            raise ValueError("CTP 合约查询返回空结果")
        data = pickle.dumps(rows, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock:
            if self._loads.get(key) is not load or load.error is not None:
                raise RuntimeError("CTP 合约目录加载代次已失效")
            load.data = data
            for old_key in list(self._loads):
                if old_key[:2] == key[:2] and old_key[2] < key[2]:
                    old_load = self._loads[old_key]
                    if old_load.data is not None or old_load.error is not None:
                        del self._loads[old_key]

    def advance(self, load: CatalogLoad) -> None:
        """记录加载者实际处理进展。"""
        with self._lock:
            if load.data is None and load.error is None:
                load.progress += 1

    def fail(self, load: CatalogLoad, message: str) -> None:
        """让这一代的所有等待者观察同一次失败。"""
        with self._lock:
            if load.data is None:
                load.error = message

    def release_owner(self, owner: str) -> None:
        """释放退出进程尚未发布的加载权。"""
        with self._lock:
            for load in self._loads.values():
                if load.owner == owner and load.data is None:
                    load.error = "CTP 合约目录加载者已退出"


class CatalogProvider(Protocol):
    """执行器的目录获取边界；查询函数只在获得加载权时执行。"""

    def get(
        self, key: CatalogKey, loader: Callable[[], CatalogRows], checkpoint: Callable[[], None] | None = None
    ) -> Mapping[str, InstrumentRecord]:
        """获取只读目录，未命中时协调加载。"""
        ...

    def progress(self, phase: str) -> None:
        """报告初始化阶段或递增记录数。"""
        ...


class LocalCatalogProvider:
    """独立执行器使用的进程内共享目录。"""

    def __init__(self, store: CatalogStore) -> None:
        self.store = store

    def get(
        self, key: CatalogKey, loader: Callable[[], CatalogRows], checkpoint: Callable[[], None] | None = None
    ) -> Mapping[str, InstrumentRecord]:
        """在进程内合并同一目录的并发加载。"""
        owner = uuid4().hex
        load = self.store.acquire(key, owner)
        if load.owner == owner:
            try:
                self.store.publish(key, load, loader())
            except BaseException as exc:
                self.store.fail(load, str(exc))
                raise
        while True:
            if checkpoint is not None:
                checkpoint()
            data, error, _ = self.store.inspect(load)
            if error is not None:
                raise RuntimeError(error)
            if data is not None:
                return decode_catalog(data)
            get_default_clock().sleep(0.05)

    def progress(self, phase: str) -> None:
        """独立执行器没有外层 IPC watchdog。"""


LOCAL_CATALOG = LocalCatalogProvider(CatalogStore())

"""独立合约目录管道；服务线程从不获取账户业务请求锁。"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from hashlib import sha256
from multiprocessing.connection import Connection
from typing import Any
from uuid import uuid4

from loguru import logger

from axile.executor.algorithms.utils.clock import clock_monotonic, get_default_clock
from axile.executor.ctp_catalog import (
    CatalogKey,
    CatalogLoad,
    CatalogRows,
    CatalogStore,
    InstrumentRecord,
    decode_catalog,
)


class CatalogSession:
    """主进程观察到的初始化进度，与业务 request_id 绑定。"""

    def __init__(self, connection: Connection, store: CatalogStore) -> None:
        self.connection = connection
        self.store = store
        self.owner = uuid4().hex
        self.request_id = ""
        self.active = False
        self.updated = 0.0
        self.started = 0.0
        self.finished = 0.0
        self.lock = threading.Lock()
        self.loads: dict[str, tuple[CatalogKey, CatalogLoad]] = {}
        self.thread = threading.Thread(target=self._serve, name="ctp-catalog", daemon=True)
        self.phase = ""
        self.phase_started = 0.0

    def snapshot(self, request_id: str) -> tuple[bool, float, float, float]:
        """读取当前请求的初始化进度，隔离旧请求。"""
        with self.lock:
            if self.request_id != request_id:
                return False, 0.0, 0.0, 0.0
            return self.active, self.updated, self.started, self.finished

    def _progress(self, message: dict[str, Any]) -> None:
        now = clock_monotonic()
        with self.lock:
            if message["op"] == "begin":
                self.request_id = message["request_id"]
                self.started = now
                self.finished = 0.0
                self.active = True
            elif message["op"] == "end":
                self.finished = now
                self.active = False
            self.updated = now
        phase = str(message.get("phase", message["op"]))
        if phase != self.phase:
            if self.phase:
                logger.debug("CTP 初始化阶段 | phase={} elapsed={:.3f}s", self.phase, now - self.phase_started)
            self.phase, self.phase_started = phase, now
        for _, load in self.loads.values():
            if load.owner == self.owner:
                self.store.advance(load)

    def _dispatch(self, message: dict[str, Any]) -> dict[str, Any]:
        op = message["op"]
        if op in {"begin", "end", "progress"}:
            self._progress(message)
            return {}
        if op == "acquire":
            key = tuple(message["key"])
            load = self.store.acquire(key, self.owner)
            self.loads.clear()
            self.loads[load.token] = (key, load)
            data, _, _ = self.store.inspect(load)
            source = sha256(repr(key[:2]).encode()).hexdigest()[:12]
            logger.info(
                "CTP 合约目录 | source={} trading_day={} state={}",
                source,
                key[2],
                "hit" if data is not None else "load" if load.owner == self.owner else "wait",
            )
            return {"token": load.token, "owner": load.owner == self.owner}
        key, load = self.loads[message["token"]]
        if op == "poll":
            data, error, progress = self.store.inspect(load)
            return {"data": data, "error": error, "progress": progress}
        if load.owner != self.owner:
            raise RuntimeError("只有目录加载者可以发布结果")
        if op == "publish":
            self.store.publish(key, load, message["rows"])
            logger.info("CTP 合约目录已缓存 | trading_day={} records={}", key[2], len(message["rows"]))
        elif op == "fail":
            self.store.fail(load, message["error"])
        else:
            raise ValueError(f"未知目录操作: {op}")
        return {}

    def _serve(self) -> None:
        try:
            while True:
                message = self.connection.recv()
                try:
                    response = self._dispatch(message)
                except Exception as exc:
                    response = {"rpc_error": str(exc)}
                self.connection.send(response)
        except (EOFError, OSError):
            pass
        finally:
            self.store.release_owner(self.owner)
            self._close_connection()

    def _close_connection(self) -> None:
        # Connection.close 的检查与系统 close 并非线程原子操作。
        with self.lock:
            if not self.connection.closed:
                self.connection.close()

    def close(self) -> None:
        """停止目录服务并唤醒失败代次的等待者。"""
        self.store.release_owner(self.owner)
        self._close_connection()
        self.thread.join(timeout=1)


class RemoteCatalogProvider:
    """worker 目录客户端；同步 RPC 由锁串行化，允许 SPI 报告进度。"""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.lock = threading.Lock()
        self.request_id = ""
        self.failed = False

    def _rpc(self, op: str, **payload: Any) -> dict[str, Any]:
        with self.lock:
            if self.failed:
                raise RuntimeError("合约目录通道已失效，必须重建 worker")
            try:
                self.connection.send({"op": op, **payload})
                if not self.connection.poll(60):
                    raise TimeoutError("主进程合约目录服务无响应")
                response = self.connection.recv()
                if not isinstance(response, dict):
                    raise ValueError("合约目录服务返回了无效响应")
            except Exception:
                # 没有收到本次响应时，不能再用该流读取任何下一次响应。
                self.failed = True
                try:
                    self.connection.close()
                except OSError as close_error:
                    logger.opt(exception=close_error).warning("失效目录管道关闭失败")
                raise
        if "rpc_error" in response:
            raise RuntimeError(response["rpc_error"])
        return response

    def begin(self) -> None:
        """标记本请求进入 CTP 初始化。"""
        self._rpc("begin", request_id=self.request_id)

    def end(self) -> None:
        """结束初始化计时，恢复业务响应预算。"""
        self._rpc("end")

    def progress(self, phase: str) -> None:
        """发送实际进展，不发送无条件保活心跳。"""
        self._rpc("progress", phase=phase)

    def get(
        self, key: CatalogKey, loader: Callable[[], CatalogRows], checkpoint: Callable[[], None] | None = None
    ) -> Mapping[str, InstrumentRecord]:
        """从主进程获取目录，获得加载权的 worker 才请求柜台。"""
        acquired = self._rpc("acquire", key=key)
        token = acquired["token"]
        if acquired["owner"]:
            # 已缓存的加载者重连也走命中路径，不能重复查询。
            status = self._rpc("poll", token=token)
            if status["data"] is None and status["error"] is None:
                try:
                    self._rpc("publish", token=token, rows=loader())
                except BaseException as exc:
                    try:
                        self._rpc("fail", token=token, error=str(exc))
                    except Exception as notification_error:
                        logger.opt(exception=notification_error).warning("目录加载失败通知发送失败，保留原始异常")
                    raise
        observed = -1
        while True:
            if checkpoint is not None:
                checkpoint()
            status = self._rpc("poll", token=token)
            if status["error"] is not None:
                raise RuntimeError(status["error"])
            if status["data"] is not None:
                return decode_catalog(status["data"])
            if status["progress"] != observed:
                observed = status["progress"]
                self.progress("等待共享目录：加载者有进展")
            get_default_clock().sleep(0.1)

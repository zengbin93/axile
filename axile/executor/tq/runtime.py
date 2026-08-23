"""在单一 owner thread 中驱动 TqApi 与 ``wait_update``."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeVar, cast

from axile.executor.tq.symbols import TQInstrument, TQSymbolResolver

T = TypeVar("T")


@dataclass(slots=True)
class _Command:
    operation: Callable[[object], object]
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: BaseException | None = None
    status: Literal["pending", "running", "finished", "cancelled"] = "pending"
    lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> bool:
        """仅让尚未取消的命令进入执行态。"""
        with self.lock:
            if self.status != "pending":
                return False
            self.status = "running"
            return True

    def cancel(self) -> bool:
        """仅取消尚未开始的命令。"""
        with self.lock:
            if self.status != "pending":
                return False
            self.status = "cancelled"
            self.done.set()
            return True

    def finish(self, *, result: object = None, error: BaseException | None = None) -> None:
        """发布已经开始执行的命令结果。"""
        with self.lock:
            if self.status != "running":
                return
            self.result = result
            self.error = error
            self.status = "finished"
            self.done.set()

    def fail_pending(self, error: BaseException) -> None:
        """运行时停止时唤醒仍在排队的调用方。"""
        with self.lock:
            if self.status != "pending":
                return
            self.error = error
            self.status = "finished"
            self.done.set()


def snapshot_entity(entity: object) -> dict[str, object]:
    """复制 TqSdk Entity 的公开字段，避免把可变 SDK 对象带出 owner thread."""
    if isinstance(entity, Mapping):
        return {str(key): value for key, value in entity.items() if not str(key).startswith("_")}
    result: dict[str, object] = {}
    for name in dir(entity):
        if name.startswith("_"):
            continue
        try:
            value = getattr(entity, name)
        except Exception:  # noqa: BLE001 - SDK Entity 属性可能动态求值
            continue
        if not callable(value):
            result[name] = value
    return result


class TQRuntime:
    """TqApi 单线程运行时与同步命令桥."""

    def __init__(self, api_factory: Callable[[], object], *, command_timeout: float = 30.0) -> None:
        self._api_factory = api_factory
        self._command_timeout = command_timeout
        self._commands: queue.Queue[_Command | None] = queue.Queue()
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._startup_error: BaseException | None = None
        self._runtime_error: BaseException | None = None
        self._close_error: BaseException | None = None
        self._api: object | None = None
        self._resolver: TQSymbolResolver | None = None
        self._subscriptions: dict[str, object] = {}
        self._listeners: list[Callable[[str, dict[str, object]], None]] = []
        self._orders: dict[str, dict[str, object]] = {}
        self._trades: dict[str, dict[str, object]] = {}
        self._thread = threading.Thread(target=self._run, name="axile-tqsdk-runtime", daemon=True)
        self._thread.start()
        if not self._ready.wait(command_timeout):
            raise TimeoutError("TqSdk 运行时初始化超时")
        if self._startup_error is not None:
            raise RuntimeError(f"TqSdk 运行时初始化失败: {self._startup_error}") from self._startup_error

    @property
    def resolver(self) -> TQSymbolResolver:
        """返回初始化阶段构建的只读 symbol 解析器."""
        if self._resolver is None:
            raise RuntimeError("TqSdk symbol 索引尚未就绪")
        return self._resolver

    def add_listener(self, listener: Callable[[str, dict[str, object]], None]) -> None:
        """注册运行时快照监听器."""
        self._listeners.append(listener)

    def is_alive(self) -> bool:
        """返回 owner thread 是否仍在运行."""
        return self._thread.is_alive() and not self._stopped.is_set()

    def call(self, operation: Callable[[object], T], *, timeout: float | None = None) -> T:
        """在 owner thread 执行同步操作并返回复制后的结果."""
        if self._stopped.is_set():
            if self._runtime_error is not None:
                raise RuntimeError(f"TqSdk 运行时异常停止: {self._runtime_error}") from self._runtime_error
            raise RuntimeError("TqSdk 运行时已关闭")
        command = _Command(cast("Callable[[object], object]", operation))
        self._commands.put(command)
        if self._stopped.is_set():
            command.fail_pending(self._stopped_error())
        wait_timeout = self._command_timeout if timeout is None else timeout
        if not command.done.wait(wait_timeout):
            if command.cancel():
                raise TimeoutError("TqSdk 命令排队超时")
            command.done.wait()
        if command.error is not None:
            raise RuntimeError(f"TqSdk 命令失败: {command.error}") from command.error
        return cast(T, command.result)

    def _stopped_error(self) -> RuntimeError:
        if self._runtime_error is not None:
            return RuntimeError(f"TqSdk 运行时异常停止: {self._runtime_error}")
        return RuntimeError("TqSdk 运行时已经停止")

    def subscribe(self, symbols: list[str]) -> None:
        """在 owner thread 创建行情实体订阅."""

        def operation(api: object) -> None:
            get_quote = getattr(api, "get_quote")
            for symbol in symbols:
                self._subscriptions.setdefault(symbol, get_quote(symbol))

        self.call(operation)

    def close(self) -> None:
        """停止事件泵并关闭 TqApi."""
        if self._stopped.is_set():
            return
        self._commands.put(None)
        self._thread.join(timeout=self._command_timeout)
        if self._thread.is_alive():
            raise TimeoutError("TqSdk 运行时关闭超时")
        if self._close_error is not None:
            raise RuntimeError(f"TqSdk 运行时关闭失败: {self._close_error}") from self._close_error

    def _build_catalog(self, api: object) -> TQSymbolResolver:
        query_quotes = getattr(api, "query_quotes")
        records: dict[str, TQInstrument] = {}
        for ins_class in ("FUTURE", "OPTION", "COMBINE"):
            for expired in (False, True):
                try:
                    symbols = query_quotes(ins_class=ins_class, expired=expired)
                except TypeError:
                    if expired:
                        continue
                    symbols = query_quotes(ins_class=ins_class)
                for raw_symbol in symbols:
                    symbol = str(raw_symbol)
                    if "." not in symbol:
                        continue
                    exchange_id, instrument_id = symbol.split(".", 1)
                    records[symbol] = TQInstrument(symbol, instrument_id, exchange_id, ins_class, expired)
        # query_quotes 不会订阅实时行情；无类别过滤的结果用于补齐指数、连续合约、
        # 股票和现货等只读品种，衍生品记录仍保留上面的精确类别与可交易属性。
        for expired in (False, True):
            try:
                symbols = query_quotes(expired=expired)
            except TypeError:
                continue
            for raw_symbol in symbols:
                symbol = str(raw_symbol)
                if symbol in records or "." not in symbol:
                    continue
                exchange_id, instrument_id = symbol.split(".", 1)
                records[symbol] = TQInstrument(
                    symbol,
                    instrument_id,
                    exchange_id,
                    "QUOTE_ONLY",
                    expired,
                )
        return TQSymbolResolver(list(records.values()))

    def _emit(self, kind: str, payload: dict[str, object]) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(kind, dict(payload))
            except Exception:
                continue

    def _pump_changes(self, api: object) -> None:
        is_changing = getattr(api, "is_changing", lambda _entity: False)
        for entity in tuple(self._subscriptions.values()):
            if is_changing(entity):
                self._emit("quote", snapshot_entity(entity))
        for kind, getter_name, previous in (
            ("order", "get_order", self._orders),
            ("trade", "get_trade", self._trades),
        ):
            getter = getattr(api, getter_name, None)
            if not callable(getter):
                continue
            rows = getter()
            if not isinstance(rows, Mapping):
                continue
            current = {str(key): snapshot_entity(value) for key, value in rows.items() if not str(key).startswith("_")}
            for key, value in current.items():
                if previous.get(key) != value:
                    self._emit(kind, value)
            previous.clear()
            previous.update(current)

    def _run(self) -> None:
        try:
            api = self._api_factory()
            self._api = api
            self._resolver = self._build_catalog(api)
        except BaseException as exc:  # noqa: BLE001 - 必须把 owner thread 初始化错误交给调用方
            self._startup_error = exc
            if self._api is not None:
                try:
                    getattr(self._api, "close")()
                except Exception:
                    pass
                self._api = None
            self._ready.set()
            self._stopped.set()
            return
        self._ready.set()
        try:
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    command = ...
                if command is None:
                    break
                if isinstance(command, _Command):
                    if command.start():
                        try:
                            result = command.operation(api)
                        except BaseException as exc:  # noqa: BLE001 - 跨线程传播 SDK 错误
                            command.finish(error=exc)
                        else:
                            command.finish(result=result)
                try:
                    wait_update = getattr(api, "wait_update")
                    try:
                        wait_update(deadline=time.time() + 0.05)
                    except TypeError:
                        wait_update()
                    self._pump_changes(api)
                except BaseException:  # noqa: BLE001 - 终止失效事件泵并让后续调用看到异常
                    raise
        except BaseException as exc:  # noqa: BLE001 - 保存事件泵异常供同步调用方读取
            self._runtime_error = exc
        finally:
            self._stopped.set()
            failure = self._stopped_error()
            while True:
                try:
                    pending = self._commands.get_nowait()
                except queue.Empty:
                    break
                if isinstance(pending, _Command):
                    pending.fail_pending(failure)
            try:
                getattr(api, "close")()
            except BaseException as exc:  # noqa: BLE001 - close 错误必须跨线程传播
                self._close_error = exc
            finally:
                self._api = None


__all__ = ["TQRuntime", "snapshot_entity"]

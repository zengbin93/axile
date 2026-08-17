"""
Execution 级共享查询运行时.

在同一次 execution 内部按查询作用域复用 orders 和 trades 快照，并对并发
请求执行 singleflight 去重。运行时只负责共享、局部失效和内存 patch，不承载
公开 API 语义，也不把订单快照和成交事件重新耦合回一个模型。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

from axile.executor.models.unified_order import TradeRecord, UnifiedOrder

type SharedQueryKey = tuple[str, ...]
type PendingOrdersSnapshotFetcher = Callable[[], list[UnifiedOrder]]
type PendingOrdersBySymbolFetcher = Callable[[str], list[UnifiedOrder]]
type TradesSnapshotFetcher = Callable[[], list[TradeRecord]]
type TradesByOrderFetcher = Callable[[str, str], list[TradeRecord]]

_QueryResultT = TypeVar("_QueryResultT")


@dataclass(slots=True)
class _InFlightQuery(Generic[_QueryResultT]):
    """
    单次进行中的共享查询.

    Attributes
    ----------
    event : threading.Event
        用于通知等待方查询完成的同步事件。
    result : list[_QueryResultT] | None
        查询成功后的结果列表。
    error : BaseException | None
        查询失败时记录的异常对象。
    """

    event: threading.Event = field(default_factory=threading.Event)
    result: list[_QueryResultT] | None = None
    error: BaseException | None = None


class ExecutionQueryRuntime:
    """
    为同一次 execution 复用查询快照并去重并发请求.

    Notes
    -----
    支持两类查询模式：

    1. ``snapshot-backed``：先抓账户级快照，再按 ``symbol`` 或 ``order_id`` 过滤复用。
    2. ``narrow-query``：渠道本身支持窄查询时，仅对完全相同的 query key 做
       singleflight。

    ``orders`` 与 ``trades`` 的缓存、失效和 patch 独立维护。
    """

    def __init__(
        self,
        *,
        fetch_pending_orders_snapshot: PendingOrdersSnapshotFetcher | None = None,
        fetch_pending_orders_by_symbol: PendingOrdersBySymbolFetcher | None = None,
        fetch_trades_snapshot: TradesSnapshotFetcher | None = None,
        fetch_trades_by_order: TradesByOrderFetcher | None = None,
    ) -> None:
        """
        初始化 execution 查询运行时.

        Parameters
        ----------
        fetch_pending_orders_snapshot : PendingOrdersSnapshotFetcher | None, default=None
            账户级挂单快照抓取函数。
        fetch_pending_orders_by_symbol : PendingOrdersBySymbolFetcher | None, default=None
            按品种抓取挂单的窄查询函数。
        fetch_trades_snapshot : TradesSnapshotFetcher | None, default=None
            账户级成交快照抓取函数。
        fetch_trades_by_order : TradesByOrderFetcher | None, default=None
            按订单抓取成交明细的窄查询函数。
        """
        self._fetch_pending_orders_snapshot = fetch_pending_orders_snapshot
        self._fetch_pending_orders_by_symbol = fetch_pending_orders_by_symbol
        self._fetch_trades_snapshot = fetch_trades_snapshot
        self._fetch_trades_by_order = fetch_trades_by_order
        self._lock = threading.Lock()
        self._snapshot_cache: dict[SharedQueryKey, list[object]] = {}
        self._inflight_queries: dict[SharedQueryKey, _InFlightQuery[object]] = {}
        self._invalidated_order_symbols: set[str] = set()
        self._invalidated_trade_symbols: set[str] = set()
        self._invalidated_trade_orders: set[tuple[str, str]] = set()
        self._orders_invalidation_version = 0
        self._trades_invalidation_version = 0

    def get_pending_orders_for_symbol(self, symbol: str) -> list[UnifiedOrder]:
        """
        获取当前 execution 中指定品种的未完成订单.

        Parameters
        ----------
        symbol : str
            需要查询的品种代码。

        Returns
        -------
        list[UnifiedOrder]
            该品种当前未完成订单列表。

        Raises
        ------
        NotImplementedError
            当既没有账户级快照抓取器，也没有按品种查询抓取器时抛出。
        """
        if self._fetch_pending_orders_snapshot is not None:
            snapshot = self._get_pending_orders_snapshot_for_symbol(symbol)
            return [order for order in snapshot if order.symbol == symbol]

        if self._fetch_pending_orders_by_symbol is None:
            raise NotImplementedError("execution query runtime 缺少 pending orders fetcher")

        fetch_pending_orders_by_symbol = self._fetch_pending_orders_by_symbol
        return self._run_shared_query(
            ("pending_orders", symbol),
            lambda: fetch_pending_orders_by_symbol(symbol),
            cache_result=False,
        )

    def get_trades_for_order(self, symbol: str, order_id: str) -> list[TradeRecord]:
        """
        获取当前 execution 中指定订单的成交明细.

        Parameters
        ----------
        symbol : str
            订单对应的品种代码。
        order_id : str
            订单标识。

        Returns
        -------
        list[TradeRecord]
            该订单对应的成交明细列表。

        Raises
        ------
        NotImplementedError
            当既没有账户级成交快照抓取器，也没有按订单查询抓取器时抛出。
        """
        if self._fetch_trades_snapshot is not None:
            snapshot = self._get_trades_snapshot_for_scope(symbol, order_id)
            return [trade for trade in snapshot if self._trade_matches_order(trade, symbol, order_id)]

        if self._fetch_trades_by_order is None:
            raise NotImplementedError("execution query runtime 缺少 trades fetcher")

        fetch_trades_by_order = self._fetch_trades_by_order
        return self._run_shared_query(
            ("query_trades", symbol, order_id),
            lambda: fetch_trades_by_order(symbol, order_id),
            cache_result=False,
        )

    def invalidate_orders(self, symbol: str | None = None) -> None:
        """
        失效挂单快照.

        Parameters
        ----------
        symbol : str | None, default=None
            需要局部失效的品种代码；为空时清除整份挂单快照。

        Notes
        -----
        传入 ``symbol`` 时仅标记该品种为脏；下次命中该品种时再触发账户级快照刷新。
        """
        with self._lock:
            self._orders_invalidation_version += 1
            if symbol is None:
                self._snapshot_cache.pop(("pending_orders_snapshot",), None)
                self._invalidated_order_symbols.clear()
                return

            self._invalidated_order_symbols.add(symbol)

    def invalidate_trades(self, symbol: str | None = None, order_id: str | None = None) -> None:
        """
        失效成交快照.

        Parameters
        ----------
        symbol : str | None, default=None
            需要失效的品种代码。
        order_id : str | None, default=None
            需要失效的订单标识；与 ``symbol`` 组合时表示更细粒度的局部失效。

        Notes
        -----
        可以按 ``symbol`` 或 ``(symbol, order_id)`` 做局部脏标记；只有命中脏
        scope 的后续查询才会触发账户级快照刷新。
        """
        with self._lock:
            self._trades_invalidation_version += 1
            if symbol is None:
                self._snapshot_cache.pop(("trades_snapshot",), None)
                self._invalidated_trade_symbols.clear()
                self._invalidated_trade_orders.clear()
                return

            if order_id is None:
                self._invalidated_trade_symbols.add(symbol)
                return

            self._invalidated_trade_orders.add((symbol, order_id))

    def invalidate_all(self) -> None:
        """清除当前 execution 内部已缓存的所有快照."""
        with self._lock:
            self._orders_invalidation_version += 1
            self._trades_invalidation_version += 1
            self._snapshot_cache.clear()
            self._invalidated_order_symbols.clear()
            self._invalidated_trade_symbols.clear()
            self._invalidated_trade_orders.clear()

    def apply_pending_order_update(self, order: UnifiedOrder) -> None:
        """
        将最新订单状态 patch 到已缓存的 pending-orders 快照.

        Parameters
        ----------
        order : UnifiedOrder
            最新订单对象。
        """
        with self._lock:
            cached_snapshot = self._snapshot_cache.get(("pending_orders_snapshot",))
            if cached_snapshot is None:
                return

            pending_orders = cast("list[UnifiedOrder]", cached_snapshot)
            updated_order = order.model_copy(deep=True)
            existing_index = self._find_pending_order_index(pending_orders, updated_order)

            if updated_order.is_active():
                if existing_index is None:
                    pending_orders.append(updated_order)
                else:
                    pending_orders[existing_index] = updated_order
            elif existing_index is not None:
                pending_orders.pop(existing_index)

            symbol = self._normalize_symbol(updated_order.symbol)
            if symbol is not None:
                self._invalidated_order_symbols.discard(symbol)

    def remove_pending_order(self, symbol: str, order_id: str) -> None:
        """
        从已缓存的 pending snapshot 中移除指定订单.

        Parameters
        ----------
        symbol : str
            品种代码。
        order_id : str
            订单标识。
        """
        with self._lock:
            cached_snapshot = self._snapshot_cache.get(("pending_orders_snapshot",))
            if cached_snapshot is not None:
                pending_orders = cast("list[UnifiedOrder]", cached_snapshot)
                pending_orders[:] = [
                    order
                    for order in pending_orders
                    if not (
                        self._normalize_symbol(order.symbol) == self._normalize_symbol(symbol)
                        and self._normalize_order_id(order.order_id) == self._normalize_order_id(order_id)
                    )
                ]

            normalized_symbol = self._normalize_symbol(symbol)
            if normalized_symbol is not None:
                self._invalidated_order_symbols.discard(normalized_symbol)

    def apply_trade_record(self, trade: TradeRecord) -> None:
        """
        将最新成交 patch 到已缓存的 trades 快照.

        Parameters
        ----------
        trade : TradeRecord
            最新成交记录。
        """
        with self._lock:
            trade_copy = trade.model_copy(deep=True)
            self._upsert_trade_in_snapshot_locked(trade_copy)

            symbol, order_id = self._resolve_trade_scope(trade_copy)
            self._clear_trade_dirty_markers(symbol, order_id)

    def _run_shared_query(
        self,
        key: SharedQueryKey,
        fetcher: Callable[[], list[_QueryResultT]],
        *,
        cache_result: bool,
        force_refresh: bool = False,
    ) -> list[_QueryResultT]:
        """
        以 singleflight 方式执行共享查询.

        Parameters
        ----------
        key : SharedQueryKey
            查询在当前 runtime 中的共享键。
        fetcher : Callable[[], list[_QueryResultT]]
            实际执行查询的抓取函数。
        cache_result : bool
            是否将结果写入快照缓存。
        force_refresh : bool, default=False
            是否绕过已有缓存强制刷新。

        Returns
        -------
        list[_QueryResultT]
            查询结果列表。

        Raises
        ------
        BaseException
            透传抓取函数执行过程中抛出的异常。
        """
        leader_query: _InFlightQuery[object] | None = None

        with self._lock:
            if cache_result and not force_refresh and key in self._snapshot_cache:
                return cast("list[_QueryResultT]", list(self._snapshot_cache[key]))

            inflight_query = self._inflight_queries.get(key)
            if inflight_query is None:
                inflight_query = _InFlightQuery[object]()
                self._inflight_queries[key] = inflight_query
                leader_query = inflight_query

        if leader_query is None:
            inflight_query.event.wait()
            if inflight_query.error is not None:
                raise inflight_query.error
            return cast("list[_QueryResultT]", list(inflight_query.result or []))

        try:
            result = list(fetcher())
        except BaseException as exc:
            with self._lock:
                self._inflight_queries.pop(key, None)
                leader_query.error = exc
                leader_query.event.set()
            raise

        with self._lock:
            if cache_result:
                self._snapshot_cache[key] = list(result)
            self._inflight_queries.pop(key, None)
            leader_query.result = cast("list[object]", list(result))
            leader_query.event.set()

        return result

    def _get_pending_orders_snapshot_for_symbol(self, symbol: str) -> list[UnifiedOrder]:
        """
        获取指定品种命中的挂单快照.

        Parameters
        ----------
        symbol : str
            品种代码。

        Returns
        -------
        list[UnifiedOrder]
            当前 execution 内部共享的挂单快照。

        Raises
        ------
        NotImplementedError
            当未配置挂单快照抓取器时抛出。
        """
        key = ("pending_orders_snapshot",)
        fetch_pending_orders_snapshot = self._fetch_pending_orders_snapshot
        if fetch_pending_orders_snapshot is None:
            raise NotImplementedError("execution query runtime 缺少 pending orders snapshot fetcher")

        with self._lock:
            refresh_required = symbol in self._invalidated_order_symbols
            invalidation_version = self._orders_invalidation_version

        snapshot = self._run_shared_query(
            key,
            fetch_pending_orders_snapshot,
            cache_result=True,
            force_refresh=refresh_required,
        )

        if refresh_required:
            with self._lock:
                if self._orders_invalidation_version == invalidation_version:
                    self._invalidated_order_symbols.clear()

        return snapshot

    def _get_trades_snapshot_for_scope(self, symbol: str, order_id: str) -> list[TradeRecord]:
        """
        获取指定范围命中的成交快照.

        Parameters
        ----------
        symbol : str
            品种代码。
        order_id : str
            订单标识。

        Returns
        -------
        list[TradeRecord]
            当前 execution 内部共享的成交快照。

        Raises
        ------
        NotImplementedError
            当未配置成交快照抓取器时抛出。
        """
        key = ("trades_snapshot",)
        fetch_trades_snapshot = self._fetch_trades_snapshot
        if fetch_trades_snapshot is None:
            raise NotImplementedError("execution query runtime 缺少 trades snapshot fetcher")

        with self._lock:
            refresh_required = (
                symbol in self._invalidated_trade_symbols or (symbol, order_id) in self._invalidated_trade_orders
            )
            invalidation_version = self._trades_invalidation_version

        snapshot = self._run_shared_query(
            key,
            fetch_trades_snapshot,
            cache_result=True,
            force_refresh=refresh_required,
        )

        if refresh_required:
            with self._lock:
                if self._trades_invalidation_version == invalidation_version:
                    self._invalidated_trade_symbols.clear()
                    self._invalidated_trade_orders.clear()

        return snapshot

    def _find_pending_order_index(
        self,
        pending_orders: list[UnifiedOrder],
        target_order: UnifiedOrder,
    ) -> int | None:
        """
        查找目标订单在挂单列表中的索引位置.

        Parameters
        ----------
        pending_orders : list[UnifiedOrder]
            当前挂单列表。
        target_order : UnifiedOrder
            需要定位的订单对象。

        Returns
        -------
        int | None
            命中时返回索引，否则返回 ``None``。
        """
        target_symbol = self._normalize_symbol(target_order.symbol)
        target_order_id = self._normalize_order_id(target_order.order_id)
        for index, order in enumerate(pending_orders):
            if (
                self._normalize_symbol(order.symbol) == target_symbol
                and self._normalize_order_id(order.order_id) == target_order_id
            ):
                return index
        return None

    def _upsert_trade_in_snapshot_locked(self, trade: TradeRecord) -> None:
        """
        在持锁状态下向成交快照插入或更新一条成交记录.

        Parameters
        ----------
        trade : TradeRecord
            需要写入快照的成交记录。
        """
        cached_snapshot = self._snapshot_cache.get(("trades_snapshot",))
        if cached_snapshot is None:
            return

        cached_trades = cast("list[TradeRecord]", cached_snapshot)
        for index, cached_trade in enumerate(cached_trades):
            if cached_trade.trade_id == trade.trade_id:
                cached_trades[index] = trade
                return

        cached_trades.append(trade)

    def _resolve_trade_scope(self, trade: TradeRecord) -> tuple[str | None, str | None]:
        """
        从成交记录中解析可用于局部失效的查询范围.

        Parameters
        ----------
        trade : TradeRecord
            成交记录对象。

        Returns
        -------
        tuple[str | None, str | None]
            解析得到的 ``(symbol, order_id)`` 范围。
        """
        symbol = self._normalize_symbol(trade.symbol) or self._normalize_symbol(trade.extra.get("symbol"))
        candidate_order_ids = {
            self._normalize_order_id(trade.order_id),
            self._normalize_order_id(trade.extra.get("order_id")),
            self._normalize_order_id(trade.extra.get("order_ref")),
            self._normalize_order_id(trade.extra.get("order_sysid")),
            self._normalize_order_id(trade.extra.get("cl_ord_id")),
            self._normalize_order_id(trade.extra.get("exchange_order_id")),
        }
        raw_candidates = trade.extra.get("order_id_candidates")
        if isinstance(raw_candidates, (list, tuple, set)):
            candidate_order_ids.update(self._normalize_order_id(candidate) for candidate in raw_candidates)

        resolved_order_id = next((candidate for candidate in candidate_order_ids if candidate is not None), None)
        return symbol, resolved_order_id

    def _clear_trade_dirty_markers(self, symbol: str | None, order_id: str | None) -> None:
        """
        清除命中成交范围的脏标记.

        Parameters
        ----------
        symbol : str | None
            品种代码。
        order_id : str | None
            订单标识。
        """
        if symbol is None:
            return
        self._invalidated_trade_symbols.discard(symbol)
        if order_id is not None:
            self._invalidated_trade_orders.discard((symbol, order_id))

    def _normalize_symbol(self, symbol: object) -> str | None:
        """
        规范化品种代码.

        Parameters
        ----------
        symbol : object
            原始品种值。

        Returns
        -------
        str | None
            去空白后的品种代码；为空时返回 ``None``。
        """
        if symbol is None:
            return None
        normalized = str(symbol).strip()
        return normalized or None

    def _normalize_order_id(self, order_id: object) -> str | None:
        """
        规范化订单标识.

        Parameters
        ----------
        order_id : object
            原始订单标识值。

        Returns
        -------
        str | None
            去空白后的订单标识；为空时返回 ``None``。
        """
        if order_id is None:
            return None
        normalized = str(order_id).strip()
        return normalized or None

    def _trade_matches_order(self, trade: TradeRecord, symbol: str, order_id: str) -> bool:
        """
        判断成交记录是否属于指定订单.

        Parameters
        ----------
        trade : TradeRecord
            待匹配的成交记录。
        symbol : str
            目标品种代码。
        order_id : str
            目标订单标识。

        Returns
        -------
        bool
            成交记录属于指定订单时返回 ``True``。
        """
        symbol_value = str(trade.extra.get("symbol") or "")
        if symbol_value != symbol:
            return False

        candidate_ids = {
            str(trade.extra.get("order_id") or ""),
            str(trade.extra.get("order_ref") or ""),
            str(trade.extra.get("order_sysid") or ""),
            str(trade.extra.get("cl_ord_id") or ""),
            str(trade.extra.get("exchange_order_id") or ""),
        }
        raw_candidates = trade.extra.get("order_id_candidates")
        if isinstance(raw_candidates, (list, tuple, set)):
            candidate_ids.update(str(candidate) for candidate in raw_candidates if candidate is not None)
        return order_id in candidate_ids

"""基于单线程 TqApi 运行时的天勤统一执行器."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, cast, override
from uuid import uuid4
from zoneinfo import ZoneInfo

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_callback import OrderUpdateCallback, PriceDataCallback, TradeRecordCallback
from axile.executor.models.unified_input import AccountConfig, TQAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_price import UnifiedPriceData
from axile.executor.tq.converters import account_to_unified, order_to_unified, quote_to_unified, trade_to_unified
from axile.executor.tq.runtime import TQRuntime, snapshot_entity

_OFFSET_MAP = {"0": "OPEN", "1": "CLOSE", "3": "CLOSETODAY", "4": "CLOSE"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _CalendarFrame(Protocol):
    def to_dict(self, orient: str) -> object: ...


class TQTradingTimeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    QUOTE_TRADING_TIME_UNAVAILABLE = "QUOTE_TRADING_TIME_UNAVAILABLE"
    CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class TQTradingTimeCheck:
    status: TQTradingTimeStatus

    @property
    def error(self) -> str | None:
        return None if self.status is TQTradingTimeStatus.OPEN else self.status.value


class TQExecutor(AbstractExecutor):
    """将 TqSdk 原语适配到 Axile 通用执行器契约."""

    def __init__(self, account_config: TQAccountConfig) -> None:
        self._runtime: TQRuntime | None = None
        self._quotes: dict[str, UnifiedPriceData] = {}
        self._order_callbacks: list[OrderUpdateCallback] = []
        self._trade_callbacks: list[TradeRecordCallback] = []
        self._price_callbacks: list[PriceDataCallback] = []
        self._lock = threading.RLock()
        self._monitoring = False
        self._closed = False
        super().__init__(TradeChannel.TQ, account_config)

    def _config(self) -> TQAccountConfig:
        if not isinstance(self.account_config, TQAccountConfig):
            raise RuntimeError("TqSdk 配置不可用")
        return self.account_config

    @staticmethod
    def _build_api(config: TQAccountConfig) -> object:
        from tqsdk import TqAccount, TqApi, TqAuth, TqKq, TqSim

        auth = TqAuth(config.tq_username, config.tq_password)
        if config.account_mode == "live":
            account = TqAccount(config.broker_name, config.account_id, config.account_password)
        elif config.account_mode == "sim":
            account = TqSim(init_balance=config.initial_balance)
        else:
            account = TqKq()
        return TqApi(account=account, auth=auth)

    @override
    def _initialize_connection(self, account_config: AccountConfig) -> None:
        if not isinstance(account_config, TQAccountConfig):
            raise TypeError("TQExecutor requires TQAccountConfig")
        runtime = TQRuntime(lambda: self._build_api(account_config))
        runtime.add_listener(self._on_runtime_event)
        self._runtime = runtime

    def _require_runtime(self) -> TQRuntime:
        if self._runtime is None:
            raise RuntimeError("TqSdk 运行时尚未初始化")
        return self._runtime

    @override
    def _verify_connection(self) -> bool:
        return not self._closed and self._runtime is not None and self._runtime.is_alive()

    @override
    def _check_trading_time(self) -> bool:
        # TQ 的交易时段必须按 symbol 判定，不能在这里用渠道级窗口提前阻断整批订单。
        return True

    @staticmethod
    def _parse_trading_time(value: object) -> int:
        if not isinstance(value, str):
            raise ValueError("交易时段不是字符串")
        parts = value.split(":")
        if len(parts) != 3:
            raise ValueError("交易时段格式无效")
        hour, minute, second = (int(part) for part in parts)
        if hour < 0 or minute not in range(60) or second not in range(60):
            raise ValueError("交易时段超出范围")
        return hour * 3600 + minute * 60 + second

    @classmethod
    def _parse_trading_time_ranges(cls, trading_time: object) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        day = getattr(trading_time, "day", None)
        night = getattr(trading_time, "night", None)
        if isinstance(trading_time, dict):
            day = trading_time.get("day")
            night = trading_time.get("night")
        if not isinstance(day, list) or not isinstance(night, list):
            raise ValueError("交易时段缺少 day/night")

        def parse_ranges(raw_ranges: list[object], *, night_session: bool) -> list[tuple[int, int]]:
            ranges: list[tuple[int, int]] = []
            for item in raw_ranges:
                if not isinstance(item, list | tuple) or len(item) != 2:
                    raise ValueError("交易时段区间无效")
                begin = cls._parse_trading_time(item[0])
                end = cls._parse_trading_time(item[1])
                if end <= begin:
                    if night_session and end < 24 * 3600:
                        end += 24 * 3600
                    else:
                        raise ValueError("交易时段结束时间无效")
                ranges.append((begin, end))
            return ranges

        return parse_ranges(day, night_session=False), parse_ranges(night, night_session=True)

    @staticmethod
    def _session_trading_date(
        day_ranges: list[tuple[int, int]],
        night_ranges: list[tuple[int, int]],
        now: datetime,
    ) -> date | None:
        seconds = now.hour * 3600 + now.minute * 60 + now.second
        if any(begin <= seconds < end for begin, end in day_ranges):
            return now.date()
        if any(begin <= seconds < end for begin, end in night_ranges):
            return now.date() + timedelta(days=1)
        overnight_seconds = seconds + 24 * 3600
        if any(begin <= overnight_seconds < end for begin, end in night_ranges):
            return now.date()
        return None

    @staticmethod
    def _calendar_trading_dates(calendar: object) -> dict[date, bool]:
        frame = cast(_CalendarFrame, calendar)
        rows = frame.to_dict("records")
        if not isinstance(rows, list):
            raise ValueError("交易日历不可读取")
        trading_dates: dict[date, bool] = {}
        for row in rows:
            if not isinstance(row, dict) or "date" not in row or "trading" not in row:
                raise ValueError("交易日历缺少字段")
            raw_date = row["date"]
            if isinstance(raw_date, datetime):
                calendar_date = raw_date.date()
            elif isinstance(raw_date, date):
                calendar_date = raw_date
            elif isinstance(raw_date, str):
                calendar_date = date.fromisoformat(raw_date[:10])
            else:
                raise ValueError("交易日历日期无效")
            if not isinstance(row["trading"], bool):
                raise ValueError("交易日历 trading 无效")
            trading_dates[calendar_date] = row["trading"]
        return trading_dates

    @staticmethod
    def _quote_trading_time(quote: object) -> object:
        if isinstance(quote, dict):
            return quote.get("trading_time")
        return getattr(quote, "trading_time")

    def _check_tq_symbol_trading_time(
        self,
        api: object,
        tq_symbol: str,
        now: datetime,
    ) -> TQTradingTimeCheck:
        try:
            day_ranges, night_ranges = self._parse_trading_time_ranges(
                self._quote_trading_time(getattr(api, "get_quote")(tq_symbol))
            )
        except Exception:
            return TQTradingTimeCheck(TQTradingTimeStatus.QUOTE_TRADING_TIME_UNAVAILABLE)

        trading_date = self._session_trading_date(day_ranges, night_ranges, now)
        if trading_date is None:
            return TQTradingTimeCheck(TQTradingTimeStatus.CLOSED)
        try:
            calendar = self._calendar_trading_dates(
                getattr(api, "get_trading_calendar")(trading_date, trading_date)
            )
        except Exception:
            return TQTradingTimeCheck(TQTradingTimeStatus.CALENDAR_UNAVAILABLE)
        if trading_date not in calendar:
            return TQTradingTimeCheck(TQTradingTimeStatus.CALENDAR_UNAVAILABLE)
        return TQTradingTimeCheck(TQTradingTimeStatus.OPEN if calendar[trading_date] else TQTradingTimeStatus.CLOSED)

    def _check_symbol_trading_times(
        self,
        symbols: list[str],
        now: datetime,
    ) -> dict[str, TQTradingTimeCheck]:
        runtime = self._require_runtime()
        pending: dict[str, str] = {}
        results: dict[str, TQTradingTimeCheck] = {}
        for symbol in dict.fromkeys(symbols):
            try:
                pending[symbol] = runtime.resolver.to_tq(symbol, for_trade=True)
            except Exception:
                results[symbol] = TQTradingTimeCheck(TQTradingTimeStatus.QUOTE_TRADING_TIME_UNAVAILABLE)
        if not pending:
            return results

        try:
            results.update(
                runtime.call(
                    lambda api: {
                        symbol: self._check_tq_symbol_trading_time(api, tq_symbol, now)
                        for symbol, tq_symbol in pending.items()
                    }
                )
            )
        except Exception:
            results.update({symbol: TQTradingTimeCheck(TQTradingTimeStatus.CALENDAR_UNAVAILABLE) for symbol in pending})
        return results

    def _check_symbol_trading_time(self, symbol: str, now: datetime | None = None) -> TQTradingTimeCheck:
        local_now = now or datetime.now(_SHANGHAI)
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=_SHANGHAI)
        return self._check_symbol_trading_times([symbol], local_now.astimezone(_SHANGHAI))[symbol]

    @override
    def _get_symbol_trading_time_blocks(self, symbols: list[str]) -> dict[str, str]:
        checks = self._check_symbol_trading_times(list(dict.fromkeys(symbols)), datetime.now(_SHANGHAI))
        return {symbol: check.error for symbol, check in checks.items() if check.error is not None}

    @override
    def _normalize_connected_standard_input(self, standard_input: UnifiedStandardInput) -> UnifiedStandardInput:
        """使用 TqSdk 合约目录将输入代码统一为 Axile 合约代码."""
        return self._require_runtime().resolver.normalize_input(standard_input)

    @override
    def _validate_input(self, standard_input: UnifiedStandardInput) -> None:
        super()._validate_input(standard_input)
        resolver = self._require_runtime().resolver
        for symbol, target in standard_input.curr_target.items():
            if target != 0:
                resolver.to_tq(symbol, for_trade=True)

    @override
    def get_account_assets(self) -> UnifiedAccountAssets:
        runtime = self._require_runtime()

        def query(api: object) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
            account = snapshot_entity(getattr(api, "get_account")())
            native_positions = getattr(api, "get_position")()
            positions = {
                str(symbol): snapshot_entity(row)
                for symbol, row in native_positions.items()
                if any(
                    float(getattr(row, name, 0) or 0) != 0
                    for name in ("pos_long_today", "pos_long_his", "pos_short_today", "pos_short_his")
                )
            }
            return account, positions

        account, positions = runtime.call(query)
        return account_to_unified(account, positions, runtime.resolver)

    def _quote_snapshot(self, symbol: str) -> dict[str, object]:
        runtime = self._require_runtime()
        tq_symbol = runtime.resolver.to_tq(symbol)
        runtime.subscribe([tq_symbol])
        return runtime.call(lambda api: snapshot_entity(getattr(api, "get_quote")(tq_symbol)))

    @override
    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        runtime = self._require_runtime()
        tq_symbols = [runtime.resolver.to_tq(symbol) for symbol in symbols]
        runtime.subscribe(tq_symbols)

        def query(api: object) -> dict[str, dict[str, object]]:
            get_quote = getattr(api, "get_quote")
            return {symbol: snapshot_entity(get_quote(symbol)) for symbol in tq_symbols}

        rows = runtime.call(query)
        result: dict[str, UnifiedPriceData] = {}
        for row in rows.values():
            quote = quote_to_unified(row, runtime.resolver)
            self._quotes[quote.symbol] = quote
            result[quote.symbol] = quote
        return result

    @override
    def _place_order_impl(
        self,
        symbol: str,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0,
        **kwargs: object,
    ) -> UnifiedOrder:
        if not float(volume).is_integer() or volume <= 0:
            raise ValueError("TqSdk 委托数量必须为正整数手")
        runtime = self._require_runtime()
        tq_symbol = runtime.resolver.to_tq(symbol, for_trade=True)
        offset_flag = str(kwargs.get("offset_flag", "0"))
        offset = _OFFSET_MAP.get(offset_flag)
        if offset is None:
            raise ValueError(f"TqSdk 不支持开平标志: {offset_flag}")

        order_id = uuid4().hex

        def submit(api: object) -> TQTradingTimeCheck | dict[str, object]:
            check = self._check_tq_symbol_trading_time(api, tq_symbol, datetime.now(_SHANGHAI))
            if check.error is not None:
                return check
            insert_order = getattr(api, "insert_order")
            arguments: dict[str, object] = {
                "symbol": tq_symbol,
                "direction": direction.value,
                "offset": offset,
                "volume": int(volume),
                "limit_price": None if order_type is OrderType.MARKET else float(price),
                "order_id": order_id,
            }
            native_order = insert_order(**arguments)
            row = snapshot_entity(native_order)
            row["order_id"] = order_id
            return row

        result = runtime.call(submit)
        if isinstance(result, TQTradingTimeCheck):
            raise AccountControlBlockedError(
                result.error or "CLOSED",
                account_id=None,
                execution_id=None,
                channel=TradeChannel.TQ,
                operation="place_order",
                symbol=symbol,
            )
        return order_to_unified(result, runtime.resolver)

    @override
    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        runtime = self._require_runtime()
        runtime.resolver.to_tq(symbol, for_trade=True)
        runtime.call(lambda api: getattr(api, "cancel_order")(order_id))
        return True

    @override
    def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
        runtime = self._require_runtime()
        rows = runtime.call(lambda api: [snapshot_entity(row) for row in getattr(api, "get_order")().values()])
        orders = [order_to_unified(row, runtime.resolver) for row in rows]
        return [order for order in orders if order.is_active() and (symbol is None or order.symbol == symbol)]

    @override
    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        runtime = self._require_runtime()
        runtime.resolver.to_tq(symbol)
        rows = runtime.call(lambda api: [snapshot_entity(row) for row in getattr(api, "get_trade")().values()])
        trades = [trade_to_unified(row, runtime.resolver) for row in rows]
        return [trade for trade in trades if trade.order_id == order_id and trade.symbol == symbol]

    @override
    def get_tick_size(self, symbol: str) -> float | None:
        value = self._quote_snapshot(symbol).get("price_tick", 0)
        try:
            tick = float(value or 0)
        except (TypeError, ValueError):
            return None
        return tick if tick > 0 else None

    @override
    def _calculate_generic_volume(
        self,
        weight: float,
        price: float,
        account_assets: UnifiedAccountAssets,
        trade_rule: dict[str, object],
        *,
        symbol: str | None = None,
    ) -> float:
        if trade_rule.get("sizing_mode", "weight") == "lots":
            return float(int(weight))
        if not symbol or price <= 0:
            return 0.0
        native = self._quote_snapshot(symbol).get("volume_multiple", 0)
        fallback = trade_rule.get("contract_multiplier", 0)
        try:
            multiplier = float(native or fallback or 0)
        except (TypeError, ValueError):
            multiplier = 0
        if multiplier <= 0:
            return 0.0
        return float(int(account_assets.total_asset * weight / (price * multiplier)))

    @override
    def initialize_websocket(self, symbols: list[str] | None = None) -> None:
        if symbols:
            runtime = self._require_runtime()
            runtime.subscribe([runtime.resolver.to_tq(symbol) for symbol in symbols])
            self._monitoring = True

    @override
    def is_monitoring(self) -> bool:
        return self._monitoring and self._verify_connection()

    def _dispatch(self, callbacks: list[Any], value: object) -> None:
        for callback in tuple(callbacks):
            try:
                callback(value)
            except Exception:
                self.logger.exception("TqSdk callback 执行失败")

    def _on_runtime_event(self, kind: str, row: dict[str, object]) -> None:
        runtime = self._require_runtime()
        if kind == "quote":
            value = quote_to_unified(row, runtime.resolver)
            self._quotes[value.symbol] = value
            self._dispatch(self._price_callbacks, value)
        elif kind == "order":
            self._dispatch(self._order_callbacks, order_to_unified(row, runtime.resolver))
        elif kind == "trade":
            self._dispatch(self._trade_callbacks, trade_to_unified(row, runtime.resolver))

    def _register(self, callbacks: list[Any], callback: Any) -> None:
        with self._lock:
            if callback not in callbacks:
                callbacks.append(callback)

    def _unregister(self, callbacks: list[Any], callback: Any) -> None:
        with self._lock:
            if callback in callbacks:
                callbacks.remove(callback)

    @override
    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        self._register(self._order_callbacks, callback)

    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """注册成交回调."""
        self._register(self._trade_callbacks, callback)

    @override
    def register_price_callback(self, callback: PriceDataCallback) -> None:
        self._register(self._price_callbacks, callback)

    @override
    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        self._unregister(self._order_callbacks, callback)

    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """注销成交回调."""
        self._unregister(self._trade_callbacks, callback)

    @override
    def unregister_price_callback(self, callback: PriceDataCallback) -> None:
        self._unregister(self._price_callbacks, callback)

    @override
    def _get_account_mark(self) -> str:
        config = self._config()
        return config.account_id or config.tq_username

    @override
    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, dict[str, object]]:
        return {symbol: {} for symbol in symbols}

    @override
    def _cleanup(self) -> None:
        """单次执行结束不关闭常驻 TqSdk 会话."""

    def close(self) -> None:
        """关闭 TqSdk owner thread 与 API."""
        if self._closed:
            return
        self._closed = True
        if self._runtime is not None:
            self._runtime.close()

    def stop(self) -> None:
        """停止执行器并关闭 TqSdk 会话."""
        self.close()


__all__ = ["TQExecutor"]

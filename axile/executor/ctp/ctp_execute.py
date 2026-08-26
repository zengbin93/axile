"""直接适配 OpenCTP TraderApi 与 MdApi 的 CTP 执行器。"""

from __future__ import annotations

import math
import re
import shutil
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TypeVar, cast, override
from zoneinfo import ZoneInfo

from openctp_ctp import thostmduserapi as md
from openctp_ctp import thosttraderapi as td

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import ExecutionReasonFamily
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.algorithms.utils import clock_now
from axile.executor.constants.order_status import OrderStatus
from axile.executor.ctp.converters import (
    account_to_unified,
    order_to_unified,
    quote_to_unified,
    stable_order_id,
    trade_to_unified,
)
from axile.executor.ctp.options import (
    OptionActionRecord,
    OptionActionStatus,
    OptionActionType,
    accept_option_action,
    build_option_cancel,
    build_option_insert,
    fail_option_action,
    finish_option_action,
    option_ref,
)
from axile.executor.ctp.requests import (
    build_authenticate,
    build_market_login,
    build_order_cancel,
    build_order_insert,
    build_query_account,
    build_query_orders,
    build_query_positions,
    build_query_settlement_confirm,
    build_query_trades,
    build_settlement_confirm,
    build_trader_login,
    resolve_offset,
)
from axile.executor.ctp.spi import MarketSpi, TraderSpi
from axile.executor.ctp_product_sessions import (
    decide_ctp_product_session,
    get_ctp_product_sessions,
)
from axile.executor.execution_engine import ExecutionEngine, _DispatchPlanningResult
from axile.executor.models.execution_result import AlgorithmResult, ExecutionStatus
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_callback import (
    UnifiedCallbackClient,
)
from axile.executor.models.unified_input import AccountConfig, CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderType, UnifiedOrder

_CZCE_FUTURE_ALIAS = re.compile(r"^(?P<product>[A-Za-z]+)(?P<year>\d{2})(?P<month>\d{2})$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ValueT = TypeVar("_ValueT")


class CtpRequestError(RuntimeError):
    pass


@dataclass
class _PendingQuery:
    rows: list[object]
    done: threading.Event
    error: Exception | None = None


@dataclass
class _Stage:
    done: threading.Event
    error: Exception | None = None


def _copy_native_row(row):
    """复制 SWIG 回调帧，解除其与 OpenCTP 复用缓冲区的绑定。"""
    values = {}
    for name in dir(row):
        if name.startswith("_") or name in {"this", "thisown"}:
            continue
        value = getattr(row, name)
        if callable(value):
            continue
        values[name] = value
    return SimpleNamespace(**values)


class CtpExecutionEngine(ExecutionEngine):
    """CTP 的品种时段筛选与 scoped cancel 编排器。"""

    def _build_symbol_algorithm_plans(self, standard_input: UnifiedStandardInput) -> _DispatchPlanningResult:
        account_assets, effective_curr_target, symbols = self._build_symbol_planning_context(standard_input)
        owner = cast("CTPExecutor", self._owner)
        allowed_symbols: list[str] = []
        planning_failures: list[AlgorithmResult] = []
        for symbol in symbols:
            reason_code = owner._get_ctp_session_block_reason(symbol)
            if reason_code is None:
                allowed_symbols.append(symbol)
                continue
            planning_failures.append(
                self._build_failed_algorithm_result(
                    symbol=symbol,
                    algorithm_name=self._get_symbol_algorithm_name(standard_input, symbol),
                    error=reason_code,
                    status=ExecutionStatus.BLOCKED,
                    account_assets=account_assets,
                    memory={
                        "symbol_decision_reason_code": reason_code,
                        "symbol_decision_reason_family": ExecutionReasonFamily.MARKET_RULE.value,
                    },
                )
            )
        return self._build_symbol_algorithm_plans_for_symbols(
            standard_input=standard_input,
            account_assets=account_assets,
            symbols=allowed_symbols,
            effective_curr_target=effective_curr_target,
            planning_failures=planning_failures,
        )

    def _derive_dispatch_error(
        self,
        status: ExecutionStatus,
        symbol_results: dict[str, AlgorithmResult],
    ) -> str | None:
        failed_results = [
            result
            for result in symbol_results.values()
            if result.status not in {ExecutionStatus.SUCCEEDED, ExecutionStatus.NOOP}
        ]
        if (
            status == ExecutionStatus.BLOCKED
            and failed_results
            and all(
                isinstance(result.memory.get("symbol_decision_reason_code"), str)
                and str(result.memory["symbol_decision_reason_code"]).startswith("CTP.SESSION.")
                for result in failed_results
            )
        ):
            return f"{len(failed_results)} 个品种因交易时段不可执行"
        return super()._derive_dispatch_error(status, symbol_results)


class CTPExecutor(AbstractExecutor, UnifiedCallbackClient):
    """直接持有 OpenCTP API 的统一执行器。"""

    def __init__(self, channel_type: TradeChannel, account_config: AccountConfig | None = None) -> None:
        self._trader_api = self._market_api = None
        self._trader_spi = self._market_spi = None
        self._pending_queries = {}
        self._instruments = {}
        self._quotes = {}
        self._order_keys = {}
        self._option_actions = {}
        self._order_callbacks = []
        self._trade_callbacks = []
        self._price_callbacks = []
        self._lock = threading.RLock()
        self._query_lock = threading.Lock()
        self._request_id = 0
        self._order_ref = 0
        self._trading_day = ""
        self._front_id = self._session_id = 0
        self._trader_connected = self._market_connected = False
        self._closed = False
        self._monitoring = False
        self._timeout = 15.0
        self._flow_dir = None
        self._auth = _Stage(threading.Event())
        self._login = _Stage(threading.Event())
        self._settlement = _Stage(threading.Event())
        self._md_login = _Stage(threading.Event())
        super().__init__(channel_type, account_config)

    def _config(self):
        if not isinstance(self.account_config, CTPAccountConfig):
            raise RuntimeError("CTP 配置不可用")
        return self.account_config

    def _next_id(self):
        with self._lock:
            self._request_id += 1
            return self._request_id

    @staticmethod
    def _error(info, name):
        code = int(getattr(info, "ErrorID", 0) or 0) if info else 0
        return CtpRequestError(f"{name}失败: ErrorID={code}, {getattr(info, 'ErrorMsg', '')}") if code else None

    @staticmethod
    def _check(code, name):
        if code != 0:
            raise CtpRequestError(f"{name}同步拒绝: return_code={code}")

    def _wait(self, stage, name):
        if not stage.done.wait(self._timeout):
            raise TimeoutError(f"{name}超时")
        if stage.error:
            raise stage.error

    @override
    def _initialize_connection(self, account_config):
        if not isinstance(account_config, CTPAccountConfig):
            raise TypeError("CTPExecutor requires CTPAccountConfig")
        required = ("broker_id", "investor_id", "password", "td_front", "md_front", "app_id", "auth_code")
        missing = [x for x in required if not getattr(account_config, x, None)]
        if missing:
            raise ValueError(f"CTP 配置缺少必填字段: {', '.join(missing)}")
        self._timeout = float(getattr(account_config, "query_timeout", 15))
        self._flow_dir = Path(tempfile.mkdtemp(prefix="axile-ctp-"))
        try:
            path = self._flow_dir / "trader"
            path.mkdir()
            self._trader_api = td.CThostFtdcTraderApi.CreateFtdcTraderApi(str(path) + "/")
            self._trader_spi = TraderSpi(self)
            self._trader_api.RegisterSpi(self._trader_spi)
            self._trader_api.RegisterFront(account_config.td_front)
            self._trader_api.SubscribePrivateTopic(td.THOST_TERT_QUICK)
            self._trader_api.SubscribePublicTopic(td.THOST_TERT_QUICK)
            self._trader_api.Init()
            self._wait(self._auth, "认证")
            self._wait(self._login, "登录")
            self._ensure_settlement_confirmed()
            rows = self._query("ReqQryInstrument", td.CThostFtdcQryInstrumentField())
            self._instruments = {str(x.InstrumentID): x for x in rows if getattr(x, "InstrumentID", "")}
            path = self._flow_dir / "market"
            path.mkdir()
            self._market_api = md.CThostFtdcMdApi.CreateFtdcMdApi(str(path) + "/")
            self._market_spi = MarketSpi(self)
            self._market_api.RegisterSpi(self._market_spi)
            self._market_api.RegisterFront(account_config.md_front)
            self._market_api.Init()
            self._wait(self._md_login, "行情登录")
        except Exception:
            self.close()
            raise

    def _trader_connected_cb(self):
        self._trader_connected = True
        req = build_authenticate(self._config())
        try:
            self._check(self._trader_api.ReqAuthenticate(req, self._next_id()), "认证")
        except Exception as e:
            self._auth.error = e
            self._auth.done.set()

    def _authenticated(self, row, info):
        self._auth.error = self._error(info, "认证")
        self._auth.done.set()
        if self._auth.error:
            return
        req = build_trader_login(self._config())
        try:
            self._check(self._trader_api.ReqUserLogin(req, self._next_id()), "登录")
        except Exception as e:
            self._login.error = e
            self._login.done.set()

    def _logged_in(self, row, info):
        self._login.error = self._error(info, "登录")
        if not self._login.error:
            self._trading_day = str(row.TradingDay)
            self._front_id = int(row.FrontID)
            self._session_id = int(row.SessionID)
            self._order_ref = int(row.MaxOrderRef or 0) + 1
        self._login.done.set()

    def _ensure_settlement_confirmed(self):
        """查询柜台状态，并仅在当前交易日未确认时发送确认。"""
        c = self._config()
        rows = self._query("ReqQrySettlementInfoConfirm", build_query_settlement_confirm(c))
        if any(str(getattr(row, "ConfirmDate", "") or "") == self._trading_day for row in rows):
            return
        req = build_settlement_confirm(self._config())
        try:
            self._check(self._trader_api.ReqSettlementInfoConfirm(req, self._next_id()), "结算确认")
        except Exception as e:
            self._settlement.error = e
            self._settlement.done.set()
        self._wait(self._settlement, "结算确认")

    def _settled(self, info):
        self._settlement.error = self._error(info, "结算确认")
        self._settlement.done.set()

    def _market_connected_cb(self):
        self._market_connected = True
        req = build_market_login(self._config())
        try:
            self._check(self._market_api.ReqUserLogin(req, self._next_id()), "行情登录")
        except Exception as e:
            self._md_login.error = e
            self._md_login.done.set()

    def _market_logged_in(self, info):
        self._md_login.error = self._error(info, "行情登录")
        self._md_login.done.set()

    def _disconnected(self, kind, reason):
        if kind == "交易":
            self._trader_connected = False
        else:
            self._market_connected = False
        self._fail_waiters(ConnectionError(f"CTP {kind}前置断线: {reason}"))

    def _fail_waiters(self, error):
        for s in (self._auth, self._login, self._settlement, self._md_login):
            if not s.done.is_set():
                s.error = error
                s.done.set()
        with self._lock:
            for p in self._pending_queries.values():
                p.error = error
                p.done.set()

    def _query(self, name, req):
        with self._query_lock:
            rid = self._next_id()
            p = _PendingQuery([], threading.Event())
            self._pending_queries[rid] = p
            try:
                self._check(getattr(self._trader_api, name)(req, rid), name)
                if not p.done.wait(self._timeout):
                    raise TimeoutError(f"{name}超时")
                if p.error:
                    raise p.error
                return list(p.rows)
            finally:
                self._pending_queries.pop(rid, None)

    def _query_response(self, row, info, rid, last):
        p = self._pending_queries.get(rid)
        if not p:
            return
        p.error = self._error(info, "查询")
        if row is not None and not p.error:
            p.rows.append(_copy_native_row(row))
        if last or p.error:
            p.done.set()

    @override
    def _verify_connection(self):
        return not self._closed and self._trader_connected and self._market_connected

    @override
    def _check_trading_time(self):
        """CTP 时段准入由 CTP 品种编排器负责。"""
        return True

    @override
    def _execution_engine(self) -> ExecutionEngine:
        return CtpExecutionEngine(self, self.require_execution_runtime())

    def _get_ctp_session_block_reason(self, symbol: str) -> str | None:
        """返回 CTP 合约当前不可交易时的稳定原因码。"""
        instrument = self._instruments.get(symbol)
        if instrument is None:
            return "CTP.SESSION.NO_METADATA"
        exchange_id = str(getattr(instrument, "ExchangeID", "") or "")
        product_id = str(getattr(instrument, "ProductID", "") or "")
        if not exchange_id or not product_id:
            return "CTP.SESSION.NO_METADATA"
        if getattr(instrument, "ProductClass", None) != td.THOST_FTDC_PC_Futures:
            return "CTP.SESSION.NO_SESSION_TABLE"
        sessions = get_ctp_product_sessions(exchange_id, product_id)
        if not sessions:
            return "CTP.SESSION.NO_SESSION_TABLE"
        now = clock_now(tz=_SHANGHAI)
        calendar = getattr(self, "_trading_calendar", None)
        calendar_id = getattr(self, "_channel_calendar_id", None)
        if calendar is None or calendar_id is None:
            return "CTP.SESSION.CALENDAR_UNAVAILABLE"
        return decide_ctp_product_session(
            sessions,
            now=now,
            calendar_is_open=lambda day: calendar.is_open(calendar_id, day),
        ).reason_code

    @override
    def _normalize_connected_standard_input(self, standard_input: UnifiedStandardInput) -> UnifiedStandardInput:
        """使用 CTP 合约目录规范化郑商所四位年份代码。"""
        return standard_input.model_copy(
            update={
                "curr_target": self._normalize_symbol_mapping("curr_target", standard_input.curr_target),
                "last_target": self._normalize_symbol_mapping("last_target", standard_input.last_target),
                "symbol_algorithms": self._normalize_symbol_mapping(
                    "symbol_algorithms", standard_input.symbol_algorithms
                ),
                "trade_rules": self._normalize_symbol_mapping("trade_rules", standard_input.trade_rules),
                "forbidden_symbols": self._normalize_symbol_list(standard_input.forbidden_symbols),
                "risk_symbols": self._normalize_symbol_list(standard_input.risk_symbols),
            }
        )

    def _normalize_symbol_mapping(self, field: str, values: Mapping[str, _ValueT]) -> dict[str, _ValueT]:
        normalized: dict[str, _ValueT] = {}
        sources: dict[str, str] = {}
        for raw_symbol, value in values.items():
            symbol = self._normalize_ctp_symbol(raw_symbol)
            if symbol in normalized and normalized[symbol] != value:
                raise ValueError(
                    f"CTP 输入字段 {field} 中的代码 {sources[symbol]} 与 {raw_symbol} 都对应 {symbol}，但配置不一致"
                )
            normalized[symbol] = value
            sources.setdefault(symbol, raw_symbol)
        return normalized

    def _normalize_symbol_list(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(self._normalize_ctp_symbol(symbol) for symbol in values))

    def _normalize_ctp_symbol(self, symbol: str) -> str:
        if symbol in self._instruments:
            return symbol
        match = _CZCE_FUTURE_ALIAS.fullmatch(symbol)
        if match is None:
            return symbol
        requested_year = 2000 + int(match.group("year"))
        trading_day = str(getattr(self, "_trading_day", ""))
        reference_year = (
            int(trading_day[:4]) if len(trading_day) >= 4 and trading_day[:4].isdigit() else datetime.now().year
        )
        native_year_digit = requested_year % 10
        nearest_year = min(
            (year for year in range(2000, 2100) if year % 10 == native_year_digit),
            key=lambda year: abs(year - reference_year),
        )
        if requested_year != nearest_year:
            return symbol
        native_symbol = f"{match.group('product')}{match.group('year')[-1]}{match.group('month')}"
        instrument = self._instruments.get(native_symbol)
        if instrument is None or str(getattr(instrument, "ExchangeID", "")) != "CZCE":
            return symbol
        if getattr(instrument, "ProductClass", None) != td.THOST_FTDC_PC_Futures:
            return symbol
        return native_symbol

    @override
    def get_account_assets(self):
        c = self._config()
        a = build_query_account(c)
        accounts = self._query("ReqQryTradingAccount", a)
        if not accounts:
            raise CtpRequestError("资金查询返回空结果")
        p = build_query_positions(c)
        return account_to_unified(accounts[-1], self._query("ReqQryInvestorPosition", p), self._instruments)

    @override
    def get_market_data(self, symbols):
        self.initialize_websocket(symbols)
        deadline = datetime.now().timestamp() + self._timeout
        while datetime.now().timestamp() < deadline:
            with self._lock:
                if all(x in self._quotes for x in symbols):
                    return {x: self._quotes[x] for x in symbols}
            threading.Event().wait(0.05)
        raise TimeoutError(f"行情等待超时: {symbols}")

    def _new_ref(self):
        with self._lock:
            r = str(self._order_ref)
            self._order_ref += 1
            return r

    @override
    def _place_order_impl(self, symbol, direction, order_type, volume, price=0, **kwargs):
        if symbol not in self._instruments:
            raise ValueError(f"未知 CTP 合约: {symbol}")
        if not isinstance(volume, (int, float)) or not float(volume).is_integer() or volume <= 0:
            raise ValueError("CTP 下单数量必须为正整数")
        tick = self.get_tick_size(symbol)
        if order_type == OrderType.LIMIT and (
            not tick or price <= 0 or not math.isclose(price / tick, round(price / tick), abs_tol=1e-7)
        ):
            raise ValueError(f"限价 {price} 不符合 tick {tick}")
        raw = kwargs.get("offset_flag", kwargs.get("offset", "open"))
        offset = resolve_offset(raw)
        reason_code = self._get_ctp_session_block_reason(symbol)
        if reason_code is not None:
            raise AccountControlBlockedError(
                reason_code,
                account_id=None,
                execution_id=None,
                channel=TradeChannel.CTP,
                operation="place_order",
                symbol=symbol,
            )
        c = self._config()
        ref = self._new_ref()
        r = build_order_insert(
            c,
            symbol=symbol,
            order_ref=ref,
            direction=direction,
            order_type=order_type,
            volume=int(volume),
            price=float(price),
            offset=offset,
        )
        oid = stable_order_id(self._trading_day, self._front_id, self._session_id, ref)
        key = {
            "order_ref": ref,
            "front_id": self._front_id,
            "session_id": self._session_id,
            "exchange_id": "",
            "order_sys_id": "",
        }
        self._order_keys[oid] = key
        try:
            self._check(self._trader_api.ReqOrderInsert(r, self._next_id()), "报单")
        except Exception:
            self._order_keys.pop(oid, None)
            raise
        return UnifiedOrder.create(
            order_id=oid,
            symbol=symbol,
            direction=direction.value,
            order_type=order_type.value,
            volume=volume,
            price=price,
            channel_type=self.channel_type,
            status=OrderStatus.SUBMITTED,
            offset_flag=offset,
            **key,
        )

    def _on_order(self, row):
        o = order_to_unified(row, trading_day=self._trading_day, front_id=self._front_id, session_id=self._session_id)
        self._order_keys[o.order_id] = {
            k: o.extra.get(k, "") for k in ("order_ref", "front_id", "session_id", "exchange_id", "order_sys_id")
        }
        self._dispatch(self._order_callbacks, o)

    def _on_trade(self, row):
        self._dispatch(
            self._trade_callbacks,
            trade_to_unified(row, trading_day=self._trading_day, front_id=self._front_id, session_id=self._session_id),
        )

    def _log_error(self, info, name):
        e = self._error(info, name)
        if e:
            self.logger.error(str(e))

    @override
    def _cancel_order_impl(self, symbol, order_id):
        key = self._order_keys.get(order_id)
        if not key:
            self._get_pending_orders_impl(symbol)
            key = self._order_keys.get(order_id)
        if not key:
            raise ValueError(f"找不到订单撤单键: {order_id}")
        r = build_order_cancel(self._config(), symbol=symbol, key=key)
        self._check(self._trader_api.ReqOrderAction(r, self._next_id()), "撤单")
        return True

    @override
    def _get_pending_orders_impl(self, symbol=None):
        r = build_query_orders(self._config(), symbol)
        orders = [
            order_to_unified(x, trading_day=self._trading_day, front_id=self._front_id, session_id=self._session_id)
            for x in self._query("ReqQryOrder", r)
        ]
        for o in orders:
            self._order_keys[o.order_id] = {
                k: o.extra.get(k, "") for k in ("order_ref", "front_id", "session_id", "exchange_id", "order_sys_id")
            }
        return [o for o in orders if o.is_active() and (not symbol or o.symbol == symbol)]

    @override
    def _query_trades_impl(self, symbol, order_id):
        r = build_query_trades(self._config(), symbol)
        ts = [
            trade_to_unified(x, trading_day=self._trading_day, front_id=self._front_id, session_id=self._session_id)
            for x in self._query("ReqQryTrade", r)
        ]
        return [x for x in ts if x.order_id == order_id]

    @override
    def get_tick_size(self, symbol):
        x = self._instruments.get(symbol)
        v = float(getattr(x, "PriceTick", 0) or 0) if x else 0
        return v if v > 0 else None

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
        """按合约乘数将目标权重换算为合法 CTP 手数。"""
        sizing_mode = trade_rule.get("sizing_mode", "weight")
        if sizing_mode == "lots":
            return self._round_lots(weight, trade_rule)
        if price <= 0:
            return 0.0
        multiplier = self._resolve_volume_multiple(symbol, trade_rule)
        if multiplier <= 0:
            return 0.0
        target = account_assets.total_asset * weight / (price * multiplier)
        return self._round_lots(target, trade_rule)

    def _resolve_volume_multiple(self, symbol: str | None, trade_rule: dict[str, object]) -> int:
        instrument = self._instruments.get(symbol) if symbol else None
        native = getattr(instrument, "VolumeMultiple", 0) if instrument is not None else 0
        if isinstance(native, int | float) and not isinstance(native, bool) and native > 0:
            return int(native)
        fallback = trade_rule.get("contract_multiplier")
        if isinstance(fallback, int | float) and not isinstance(fallback, bool) and fallback > 0:
            return int(fallback)
        return 0

    @staticmethod
    def _round_lots(volume: float, trade_rule: dict[str, object]) -> float:
        precision = trade_rule.get("quantity_precision")
        if isinstance(precision, int) and not isinstance(precision, bool):
            return round(volume, precision)
        minimum = trade_rule.get("最小交易单位", 1)
        lot = float(minimum) if isinstance(minimum, int | float) and not isinstance(minimum, bool) else 1.0
        if lot > 1:
            sign = 1.0 if volume >= 0 else -1.0
            return sign * (int(abs(volume) / lot) * lot)
        return float(int(volume)) if volume >= 0 else float(-int(-volume))

    def _on_quote(self, row):
        q = quote_to_unified(row)
        self._quotes[q.symbol] = q
        self._dispatch(self._price_callbacks, q)

    @override
    def initialize_websocket(self, symbols=None):
        if not symbols:
            return
        unknown = [x for x in symbols if x not in self._instruments]
        if unknown:
            raise ValueError(f"未知 CTP 合约: {unknown}")
        encoded = [symbol.encode() for symbol in symbols]
        self._check(self._market_api.SubscribeMarketData(encoded, len(encoded)), "行情订阅")
        self._monitoring = True

    def _dispatch(self, callbacks, value):
        for cb in list(callbacks):
            try:
                cb(value)
            except Exception:
                self.logger.exception("CTP callback 执行失败")

    def _register(self, items, cb):
        with self._lock:
            if cb not in items:
                items.append(cb)

    def _unregister(self, items, cb):
        with self._lock:
            if cb in items:
                items.remove(cb)

    def register_order_callback(self, cb):
        """注册订单回调。"""
        self._register(self._order_callbacks, cb)

    def register_trade_callback(self, cb):
        """注册成交回调。"""
        self._register(self._trade_callbacks, cb)

    def register_price_callback(self, cb):
        """注册行情回调。"""
        self._register(self._price_callbacks, cb)

    def unregister_order_callback(self, cb):
        """注销订单回调。"""
        self._unregister(self._order_callbacks, cb)

    def unregister_trade_callback(self, cb):
        """注销成交回调。"""
        self._unregister(self._trade_callbacks, cb)

    def unregister_price_callback(self, cb):
        """注销行情回调。"""
        self._unregister(self._price_callbacks, cb)

    def is_monitoring(self):
        """返回行情监控状态。"""
        return self._monitoring and self._verify_connection()

    def submit_option_action(self, symbol, action, volume, **kwargs):
        """提交期权指令。"""
        if symbol not in self._instruments:
            raise ValueError(f"未知 CTP 合约: {symbol}")
        if not isinstance(volume, int) or volume <= 0:
            raise ValueError("期权指令数量必须为正整数")
        c = self._config()
        ref = self._new_ref()
        kind = OptionActionType(action)
        record = OptionActionRecord(ref, symbol, kind, volume, submit_time=datetime.now().isoformat())
        req, name = build_option_insert(
            broker_id=c.broker_id,
            investor_id=c.investor_id,
            order_ref=ref,
            instrument_id=symbol,
            action=kind,
            volume=volume,
        )
        self._option_actions[ref] = record
        try:
            self._check(getattr(self._trader_api, name)(req, self._next_id()), name)
        except Exception:
            self._option_actions.pop(ref, None)
            raise
        return record

    def cancel_option_action(self, ref):
        """撤销期权指令。"""
        record = self._option_actions.get(ref)
        if not record:
            raise KeyError(f"未知期权指令: {ref}")
        c = self._config()
        req, name = build_option_cancel(record, broker_id=c.broker_id, investor_id=c.investor_id)
        self._check(getattr(self._trader_api, name)(req, self._next_id()), name)
        record.status = OptionActionStatus.CANCELLING
        return True

    def get_option_action_status(self, ref):
        """返回当前进程中的期权指令状态。"""
        return self._option_actions.get(ref)

    def _option_response(self, row, info):
        ref = option_ref(row)
        r = self._option_actions.get(ref)
        if r:
            if self._error(info, "期权指令"):
                self._option_actions[ref] = fail_option_action(r, info, "front")
            else:
                self._option_actions[ref] = accept_option_action(r)

    def _option_error(self, row, info):
        ref = option_ref(row)
        r = self._option_actions.get(ref)
        if r:
            self._option_actions[ref] = fail_option_action(r, info, "exchange")

    def _option_return(self, row):
        ref = option_ref(row)
        r = self._option_actions.get(ref)
        if not r:
            return
        self._option_actions[ref] = finish_option_action(r, row)

    def _option_cancel_response(self, row, info):
        ref = option_ref(row)
        r = self._option_actions.get(ref)
        if r and self._error(info, "期权撤销"):
            self._option_actions[ref] = fail_option_action(r, info, "front")

    def is_exercise_valuable(self, symbol):
        """根据标的现价和行权价判断内在价值。"""
        x = self._instruments.get(symbol)
        if not x:
            raise ValueError(f"未知 CTP 合约: {symbol}")
        u = str(x.UnderlyingInstrID)
        prices = self.get_market_data([symbol, u])
        return (
            prices[u].last_price > float(x.StrikePrice)
            if x.OptionsType == td.THOST_FTDC_CP_CallOptions
            else prices[u].last_price < float(x.StrikePrice)
        )

    @override
    def _get_account_mark(self):
        c = self._config()
        return f"ctp_{c.broker_id}_{c.investor_id}"

    @override
    def _get_default_trade_rules_for_empty(self, symbols):
        return {x: {"price": "PASSIVE", "offset_priority": "今昨,开", "max_single_order_size": 50} for x in symbols}

    @override
    def _cleanup(self):
        self.close()

    def close(self):
        """按行情、交易顺序幂等释放 API。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._monitoring = False
        self._fail_waiters(ConnectionError("CTPExecutor 已关闭"))
        for name in ("_market_api", "_trader_api"):
            api = getattr(self, name)
            if api:
                try:
                    api.RegisterSpi(None)
                    api.Release()
                except Exception:
                    self.logger.exception("释放 OpenCTP API 失败")
                setattr(self, name, None)
        self._market_connected = self._trader_connected = False
        if self._flow_dir:
            shutil.rmtree(self._flow_dir, ignore_errors=True)
            self._flow_dir = None

    @override
    def stop(self):
        self.close()


__all__ = ["CTPExecutor"]

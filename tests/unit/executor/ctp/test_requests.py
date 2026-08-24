"""CTP 原生请求字段构造与调用测试。"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openctp_ctp import thosttraderapi as td

from axile.executor.ctp.ctp_execute import CTPExecutor, _PendingQuery, _Stage
from axile.executor.ctp.requests import (
    build_order_cancel,
    build_order_insert,
    build_query_settlement_confirm,
    resolve_offset,
)
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import CTPAccountConfig
from axile.executor.models.unified_order import OrderDirection, OrderType


@pytest.fixture
def config() -> CTPAccountConfig:
    """返回不连接柜台的最小 CTP 配置。"""
    return CTPAccountConfig(
        broker_id="9999",
        investor_id="100001",
        password="secret",
        td_front="tcp://td:10001",
        md_front="tcp://md:10002",
        app_id="app-id",
        auth_code="auth-code",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("open", td.THOST_FTDC_OF_Open),
        ("平", td.THOST_FTDC_OF_Close),
        ("close_today", td.THOST_FTDC_OF_CloseToday),
        ("平昨", td.THOST_FTDC_OF_CloseYesterday),
    ],
)
def test_resolve_offset_maps_algorithm_values(value: str, expected: str) -> None:
    assert resolve_offset(value) == expected


def test_resolve_offset_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="不支持的开平标志"):
        resolve_offset("invalid")


def test_build_order_insert_populates_native_fields(config: CTPAccountConfig) -> None:
    request = build_order_insert(
        config,
        symbol="rb2610",
        order_ref="42",
        direction=OrderDirection.BUY,
        order_type=OrderType.LIMIT,
        volume=3,
        price=3210.0,
        offset=td.THOST_FTDC_OF_CloseToday,
    )

    assert request.BrokerID == "9999"
    assert request.InstrumentID == "rb2610"
    assert request.Direction == td.THOST_FTDC_D_Buy
    assert request.CombOffsetFlag == td.THOST_FTDC_OF_CloseToday
    assert request.OrderPriceType == td.THOST_FTDC_OPT_LimitPrice
    assert request.VolumeTotalOriginal == 3
    assert request.LimitPrice == 3210.0


def test_target_weight_uses_contract_multiplier_and_integer_lots() -> None:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor._instruments = {"rb2610": SimpleNamespace(VolumeMultiple=10)}
    assets = UnifiedAccountAssets(available_cash=21_000_000, total_asset=21_000_000, market_value=0, positions=[])

    volume = executor._calculate_generic_volume(0.0001, 3036.0, assets, {}, symbol="rb2610")

    assert volume == 0.0


def test_lots_sizing_mode_preserves_explicit_integer_target() -> None:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor._instruments = {}
    assets = UnifiedAccountAssets(available_cash=1, total_asset=1, market_value=0, positions=[])

    volume = executor._calculate_generic_volume(3, 0, assets, {"sizing_mode": "lots"}, symbol="option")

    assert volume == 3.0


def test_build_order_cancel_prefers_front_session_key(config: CTPAccountConfig) -> None:
    request = build_order_cancel(
        config,
        symbol="rb2610",
        key={
            "order_ref": "42",
            "front_id": 7,
            "session_id": 8,
            "exchange_id": "SHFE",
            "order_sys_id": "100",
        },
    )

    assert request.OrderRef == "42"
    assert request.FrontID == 7
    assert request.SessionID == 8
    assert request.ExchangeID == ""
    assert request.OrderSysID == ""


def test_build_order_cancel_falls_back_to_exchange_key(config: CTPAccountConfig) -> None:
    request = build_order_cancel(
        config,
        symbol="rb2610",
        key={
            "order_ref": "42",
            "front_id": 0,
            "session_id": 0,
            "exchange_id": "SHFE",
            "order_sys_id": "100",
        },
    )

    assert request.ExchangeID == "SHFE"
    assert request.OrderSysID == "100"


def test_trader_login_uses_openctp_677_signature(config: CTPAccountConfig) -> None:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor.account_config = config
    executor._trader_api = Mock()
    executor._trader_api.ReqUserLogin.return_value = 0
    executor._lock = threading.RLock()
    executor._request_id = 0
    executor._auth = _Stage(threading.Event())
    executor._login = _Stage(threading.Event())

    executor._authenticated(None, None)

    args = executor._trader_api.ReqUserLogin.call_args.args
    assert args[1:] == (1,)


def test_query_response_copies_reused_swig_frame() -> None:
    executor = CTPExecutor.__new__(CTPExecutor)
    pending = _PendingQuery([], threading.Event())
    executor._pending_queries = {7: pending}
    row = td.CThostFtdcInstrumentField()
    row.InstrumentID = "rb2610"

    executor._query_response(row, None, 7, False)
    row.InstrumentID = "ag2612"
    executor._query_response(row, None, 7, True)

    assert [item.InstrumentID for item in pending.rows] == ["rb2610", "ag2612"]


def test_market_subscription_encodes_instrument_ids() -> None:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor._instruments = {"rb2610": object()}
    executor._market_api = Mock()
    executor._market_api.SubscribeMarketData.return_value = 0
    executor._monitoring = False

    executor.initialize_websocket(["rb2610"])

    executor._market_api.SubscribeMarketData.assert_called_once_with([b"rb2610"], 1)
    assert executor._monitoring is True


def test_query_settlement_confirm_populates_account_key(config: CTPAccountConfig) -> None:
    request = build_query_settlement_confirm(config)

    assert request.BrokerID == config.broker_id
    assert request.InvestorID == config.investor_id


def _settlement_executor(config: CTPAccountConfig) -> CTPExecutor:
    executor = CTPExecutor.__new__(CTPExecutor)
    executor.account_config = config
    executor._trading_day = "20260824"
    executor._trader_api = Mock()
    executor._timeout = 0.1
    executor._lock = threading.RLock()
    executor._request_id = 0
    executor._settlement = _Stage(threading.Event())
    return executor


def test_settlement_query_skips_confirmation_for_current_trading_day(config: CTPAccountConfig) -> None:
    executor = _settlement_executor(config)
    executor._query = Mock(return_value=[SimpleNamespace(ConfirmDate="20260824")])

    executor._ensure_settlement_confirmed()

    executor._trader_api.ReqSettlementInfoConfirm.assert_not_called()


def test_settlement_query_confirms_when_current_day_is_missing(config: CTPAccountConfig) -> None:
    executor = _settlement_executor(config)
    executor._query = Mock(return_value=[SimpleNamespace(ConfirmDate="20260821")])

    def confirm(_request: object, _request_id: int) -> int:
        executor._settled(None)
        return 0

    executor._trader_api.ReqSettlementInfoConfirm.side_effect = confirm

    executor._ensure_settlement_confirmed()

    executor._trader_api.ReqSettlementInfoConfirm.assert_called_once()

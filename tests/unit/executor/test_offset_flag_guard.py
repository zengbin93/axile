"""Issue #53：期货渠道缺失 offset_flag 时拒绝默认开仓 + 算法层补齐开平标志."""

from __future__ import annotations

import pytest

from axile.executor.models.unified_order import OrderDirection, OrderType


def _started_ctp_executor(monkeypatch):
    from tests.unit.executor.ctp.test_connection_recovery import ScriptedBroker

    broker = ScriptedBroker(monkeypatch)
    executor = broker.start()
    executor.initialize_websocket(["ag2612"])
    broker.quote()
    monkeypatch.setattr(executor, "_get_ctp_session_block_reason", lambda _symbol: None)
    return broker, executor


def test_ctp_place_order_without_offset_flag_is_rejected(monkeypatch):
    """CTP 渠道在 offset_flag 与 position_side 均缺失时必须拒绝，而非默认开仓."""
    broker, executor = _started_ctp_executor(monkeypatch)
    try:
        with pytest.raises(ValueError, match="offset_flag"):
            executor._place_order_impl("ag2612", OrderDirection.SELL, OrderType.LIMIT, 1, 9000)
        broker.trader.ReqOrderInsert.assert_not_called()
    finally:
        executor.close()


def test_ctp_place_order_derives_close_from_position_side(monkeypatch):
    """CTP 渠道缺失 offset_flag 但携带 position_side 时推导为平仓."""
    from openctp_ctp import thosttraderapi as td

    broker, executor = _started_ctp_executor(monkeypatch)
    try:
        order = executor._place_order_impl(
            "ag2612", OrderDirection.SELL, OrderType.LIMIT, 1, 9000, position_side="LONG"
        )
        assert order.extra["offset_flag"] == td.THOST_FTDC_OF_Close
    finally:
        executor.close()


def _started_tq_executor(monkeypatch):
    from axile.executor.models.unified_input import TQAccountConfig
    from axile.executor.tq.tq_execute import TQExecutor, TQTradingTimeCheck, TQTradingTimeStatus
    from tests.unit.executor.tq.test_executor import FakeApi

    api = FakeApi()
    monkeypatch.setattr(TQExecutor, "_build_api", staticmethod(lambda _config: api))
    executor = TQExecutor(TQAccountConfig(account_mode="kq", tq_username="u", tq_password="p"))
    executor._initialize_connection(executor.account_config)
    monkeypatch.setattr(
        executor,
        "_check_tq_symbol_trading_time",
        lambda _api, _sessions, _now: TQTradingTimeCheck(TQTradingTimeStatus.OPEN),
    )
    return executor, api


def test_tq_place_order_without_offset_flag_is_rejected(monkeypatch):
    """TQ 渠道在 offset_flag 与 position_side 均缺失时必须拒绝，而非默认 OPEN."""
    executor, _api = _started_tq_executor(monkeypatch)
    try:
        with pytest.raises(ValueError, match="offset_flag"):
            executor._place_order_impl("rb2610", OrderDirection.SELL, OrderType.LIMIT, 1, 3200)
    finally:
        executor.close()


def test_tq_place_order_derives_close_from_position_side(monkeypatch):
    """TQ 渠道缺失 offset_flag 但携带 position_side 时推导为 CLOSE."""
    executor, api = _started_tq_executor(monkeypatch)
    try:
        order = executor._place_order_impl(
            "rb2610", OrderDirection.SELL, OrderType.LIMIT, 1, 3200, position_side="LONG"
        )
        assert api.insert_args["offset"] == "CLOSE"
        assert order.symbol == "rb2610"
    finally:
        executor.close()


def test_tq_offset_map_accepts_ctp_semantic_flags():
    """算法层按 CTP 语义传递的 open/close/close_today 标志须被 TQ 正确映射."""
    from axile.executor.tq.tq_execute import _OFFSET_MAP

    assert _OFFSET_MAP["open"] == "OPEN"
    assert _OFFSET_MAP["close"] == "CLOSE"
    assert _OFFSET_MAP["close_today"] == "CLOSETODAY"
    assert _OFFSET_MAP["close_yesterday"] == "CLOSE"

"""CTP 成交关联必须跨会话稳定，未知身份保留而不猜测。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from axile.executor.ctp.ctp_execute import CtpRequestError
from tests.unit.executor.ctp.test_connection_recovery import ScriptedBroker


@pytest.fixture
def broker(monkeypatch):
    driver = ScriptedBroker(monkeypatch)
    driver.start()
    yield driver
    driver.executor.close()


def changed(row, **fields):
    return SimpleNamespace(**(vars(row) | fields))


def test_old_session_same_ref_uses_exchange_identity_and_history(broker, monkeypatch):
    executor = broker.executor
    received = []
    executor.register_trade_callback(received.append)
    # 当前会话复用 OrderRef，但系统编号不同。
    executor._on_order(changed(broker.order, SessionID=2, OrderSysID="new"))
    executor._on_trade(broker.trade)
    executor._on_trade(broker.trade)
    assert [trade.order_id for trade in received] == ["20260909:7:1:10"]
    monkeypatch.setattr(executor, "_query", lambda *args: [broker.trade])
    history = executor._query_trades_impl("ag2612", "20260909:7:1:10")
    assert [trade.order_id for trade in history] == [received[0].order_id]


def test_trade_before_order_is_retained_blocks_new_orders_and_replayed_once(broker):
    executor = broker.executor
    received = []
    executor.register_trade_callback(received.append)
    trade = changed(broker.trade, OrderSysID="late", TradeID="T2")
    executor._on_trade(trade)
    executor._on_trade(trade)
    assert not received
    assert len(executor._unassociated_trades) == 1
    with pytest.raises(CtpRequestError, match="未归属"):
        executor._require_new_order_ready()
    assert executor._invalid_reason is None
    executor._on_order(changed(broker.order, OrderSysID="late", OrderRef="11"))
    assert [trade.order_id for trade in received] == ["20260909:7:1:11"]
    assert not executor._unassociated_trades
    executor._on_trade(trade)
    executor._on_order(changed(broker.order, OrderSysID="late", OrderRef="11"))
    assert len(received) == 1
    executor._require_new_order_ready()


def test_same_system_id_on_other_exchange_does_not_alias(broker):
    executor = broker.executor
    executor._remember_order(changed(broker.order, ExchangeID="DCE", SessionID=5))
    first = executor._convert_trade(broker.trade)
    second = executor._convert_trade(changed(broker.trade, ExchangeID="DCE"))
    assert first.order_id == "20260909:7:1:10"
    assert second.order_id == "20260909:7:5:10"


def test_ambiguous_mapping_cannot_overwrite_previous_identity(broker):
    executor = broker.executor
    with pytest.raises(CtpRequestError, match="歧义"):
        executor._remember_order(changed(broker.order, SessionID=9))
    with pytest.raises(CtpRequestError, match="唯一"):
        executor._convert_trade(broker.trade)
    assert len(executor._unassociated_trades) == 1
    with pytest.raises(CtpRequestError, match="歧义"):
        executor._require_new_order_ready()


def test_other_trading_day_cannot_use_current_mapping(broker):
    with pytest.raises(CtpRequestError, match="交易日"):
        broker.executor._convert_trade(changed(broker.trade, TradingDay="20260908"))


def test_distinct_trade_ids_with_same_fill_are_both_delivered(broker):
    callback = Mock()
    broker.executor.register_trade_callback(callback)
    broker.executor._on_trade(broker.trade)
    broker.executor._on_trade(changed(broker.trade, TradeID="T2"))
    broker.executor._on_trade(broker.trade)
    assert callback.call_count == 2
    assert {call.args[0].trade_id for call in callback.call_args_list} == {"T1", "T2"}

"""真实 OpenCTP 请求及 SPI 到会话/跟踪器的离线链路。"""

from types import SimpleNamespace

import pytest
from openctp_ctp import thosttraderapi as td

from axile.executor.algorithms.utils.order_tracker import OrderTracker
from axile.executor.constants.order_status import OrderStatus
from axile.executor.ctp.converters import stable_order_id
from axile.executor.execution_session import ExecutionSession
from axile.executor.models.unified_order import OrderDirection, OrderType
from tests.unit.executor.ctp.test_connection_recovery import ScriptedBroker


@pytest.mark.parametrize(("current_session", "old_session"), [(2, 1), (-12345, 12345), (12345, -12345)])
@pytest.mark.parametrize("callback", ["OnRspOrderInsert", "OnErrRtnOrderInsert"])
def test_native_reject_replays_only_into_matching_session(monkeypatch, callback, current_session, old_session):
    broker = ScriptedBroker(monkeypatch, session=current_session)
    executor = broker.start()
    try:
        executor.initialize_websocket(["ag2612"])
        broker.quote()
        monkeypatch.setattr(executor, "_get_ctp_session_block_reason", lambda _symbol: None)
        session = ExecutionSession(executor, "ag2612")
        tracker = OrderTracker(session)
        session.register_order_callback(tracker.on_order_update)
        captured = []

        def reject(request, rid):
            assert isinstance(request, td.CThostFtdcInputOrderField)
            captured.append(request)
            info = td.CThostFtdcRspInfoField()
            info.ErrorID = 31
            info.ErrorMsg = "offline rejection"
            handler = getattr(broker.trader_spi, callback)
            if callback == "OnRspOrderInsert":
                handler(request, info, rid, True)
            else:
                handler(request, info)
            return 0

        broker.trader.ReqOrderInsert.side_effect = reject
        current = session.place_order(OrderDirection.BUY, OrderType.LIMIT, 1, 9000, offset_flag="open")
        old_id = stable_order_id(broker.day, 7, old_session, captured[0].OrderRef)
        old = current.model_copy(update={"order_id": old_id})
        tracker.add_order(old)
        executor._order_keys[old_id] = {"order_ref": captured[0].OrderRef, "front_id": 7, "session_id": old_session}
        tracker.add_order(current)
        assert tracker.completed_orders[current.order_id].status == OrderStatus.REJECTED
        reject(captured[0], 100)
        assert tracker.completed_orders[current.order_id].status == OrderStatus.REJECTED
        assert old_id in tracker.pending_orders
        assert not tracker._early_order_updates
        explicit = SimpleNamespace(
            OrderRef=captured[0].OrderRef,
            TradingDay=broker.day,
            FrontID=7,
            SessionID=old_session,
            InstrumentID="ag2612",
            VolumeTotalOriginal=1,
        )
        broker.trader_spi.OnErrRtnOrderInsert(explicit, SimpleNamespace(ErrorID=31))
        assert tracker.completed_orders[old_id].status == OrderStatus.REJECTED
        assert tracker.all_done_event.is_set()
        instrument = executor._instruments["ag2612"]
        instrument.MinLimitOrderVolume = 3
        instrument.MaxLimitOrderVolume = 10
        instrument.MinMarketOrderVolume = 1
        instrument.MaxMarketOrderVolume = 3
        assert session.get_order_volume_bounds(OrderType.LIMIT) == (3, 10)
        assert session.get_order_volume_bounds(OrderType.MARKET) == (1, 3)
        assert session.get_max_order_volume(OrderType.MARKET) == 3
        with pytest.raises(ValueError, match="最小"):
            session.place_order(OrderDirection.BUY, OrderType.LIMIT, 2, 9000, offset_flag="open")
        assert len(captured) == 2
    finally:
        executor.close()

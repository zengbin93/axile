"""F09：异步报单拒绝身份解析与终态字段（不导入 openctp）。"""

from __future__ import annotations

from types import SimpleNamespace

from axile.executor.order_insert_rejects import (
    insert_error_detail,
    rejected_order_update,
    resolve_insert_reject_order_id,
)


def _stable_order_id(trading_day: str, front_id: int, session_id: int, order_ref: str) -> str:
    return f"{trading_day}:{front_id}:{session_id}:{order_ref}"


def test_F09_insert_error_detail_ignores_success() -> None:
    assert insert_error_detail(None) is None
    assert insert_error_detail(SimpleNamespace(ErrorID=0, ErrorMsg="ok")) is None


def test_F09_insert_error_detail_reads_code_and_message() -> None:
    assert insert_error_detail(SimpleNamespace(ErrorID=31, ErrorMsg="synthetic reject")) == (
        31,
        "synthetic reject",
    )


def test_F09_resolve_order_id_from_registered_keys() -> None:
    order_id = "20260909:1:10:7"
    keys = {order_id: {"order_ref": "7", "front_id": 1, "session_id": 10}}
    row = SimpleNamespace(OrderRef="7", TradingDay="20260909")
    assert (
        resolve_insert_reject_order_id(
            row=row,
            order_keys=keys,
            trading_day="20260909",
            front_id=1,
            session_id=20,
            stable_order_id=_stable_order_id,
        )
        == order_id
    )


def test_F09_resolve_order_id_early_reject_uses_current_session() -> None:
    row = SimpleNamespace(OrderRef="7", TradingDay="20260909")
    assert (
        resolve_insert_reject_order_id(
            row=row,
            order_keys={},
            trading_day="20260909",
            front_id=1,
            session_id=20,
            stable_order_id=_stable_order_id,
        )
        == "20260909:1:20:7"
    )


def test_F09_rejected_order_update_keeps_error_identity() -> None:
    fields = rejected_order_update(
        order_id="o1",
        symbol="rb2610",
        direction="SELL",
        order_type="LIMIT",
        volume=1,
        price=3200,
        channel_type="ctp",
        offset_flag="0",
        error_id=31,
        error_msg="synthetic reject",
        source="OnRspOrderInsert",
    )
    assert fields["status"] == "已拒绝"
    assert fields["error_id"] == 31
    assert fields["error_msg"] == "synthetic reject"
    assert fields["reject_source"] == "OnRspOrderInsert"

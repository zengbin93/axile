"""CTP 期权指令快照转换测试。"""

from types import SimpleNamespace

from axile.executor.ctp.options import (
    OptionActionRecord,
    OptionActionStatus,
    OptionActionType,
    accept_option_action,
    fail_option_action,
    finish_option_action,
)


def test_option_updates_replace_record_instead_of_mutating() -> None:
    original = OptionActionRecord("1", "m2610-C-3000", OptionActionType.EXERCISE, 1)

    accepted = accept_option_action(original)
    failed = fail_option_action(accepted, SimpleNamespace(ErrorID=42, ErrorMsg="rejected"), "exchange")

    assert original.status is OptionActionStatus.PENDING
    assert accepted.status is OptionActionStatus.SUBMITTED
    assert failed.status is OptionActionStatus.FAILED
    assert failed.error_id == 42
    assert failed.error_source == "exchange"


def test_finish_option_action_preserves_original_extra() -> None:
    original = OptionActionRecord(
        "2",
        "m2610-C-3000",
        OptionActionType.ABANDON,
        1,
        extra={"client": "test"},
    )
    row = SimpleNamespace(ExchangeID="DCE", ExecOrderSysID=" 10 ", OptionSelfCloseSysID="")

    finished = finish_option_action(original, row)

    assert finished.status is OptionActionStatus.ABANDONED
    assert finished.extra == {
        "client": "test",
        "exchange_id": "DCE",
        "exec_order_sys_id": "10",
        "option_self_close_sys_id": "",
    }
    assert original.extra == {"client": "test"}

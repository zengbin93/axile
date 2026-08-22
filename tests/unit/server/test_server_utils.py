"""服务端通用工具函数测试。"""

import asyncio

import pytest
from pydantic import ValidationError

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import ExecutionKind, ExecutionTaskStatus
from axile.server import channel_capabilities
from axile.server import utils as server_utils
from axile.server.db.models import Account
from axile.server.db.models.account import AccountUpdate
from axile.server.execution import records as execution_records


class _FakeWriteSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.refreshed: list[object] = []

    async def __aenter__(self) -> "_FakeWriteSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)


def _build_account() -> Account:
    return Account(
        id=1,
        name="ctp-testnet-sim",
        market="期货",
        trade_channel=TradeChannel.CTP,
        account_control_preset="default",
        account_control_override=None,
        account_config={"broker_id": "9999", "investor_id": "test", "password": "test"},
        is_started=True,
        cron_expr="*/5 * * * *",
        remark=None,
        brokerage="ctp",
        weight_precision=0.001,
        long_leverage=1.0,
        short_leverage=1.0,
        algorithm={"method": "SINGLE-MAKER"},
        empty_positions_algorithm=None,
        trade_rules={},
        forbidden_symbols=[],
        risk_symbols=[],
        feishu_key=None,
        portfolio_id=None,
        write_empty_record=0,
    )


def test_parse_cron_expr_supports_multiple_triggers() -> None:
    triggers = server_utils.parse_cron_expr("*/5 * * * * | 0 9 * * 1")

    assert len(triggers) == 2


def test_parse_cron_expr_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="空表达式"):
        server_utils.parse_cron_expr("   ")


def test_is_blank_cron_expr_treats_empty_as_manual_only() -> None:
    """空 / 空白 cron 表示仅手动，调度路径应短路而非 parse."""
    assert server_utils.is_blank_cron_expr("") is True
    assert server_utils.is_blank_cron_expr("   ") is True
    assert server_utils.is_blank_cron_expr(None) is True
    assert server_utils.is_blank_cron_expr("*/5 * * * *") is False


@pytest.mark.parametrize("expr", ["* * * * *", "0 8 * * *", "0 8 * * * | 0 20 * * 1-5", ""])
def test_account_update_accepts_valid_or_blank_cron(expr: str) -> None:
    """合法 / 多段 / 空（仅手动）cron 应通过 AccountUpdate 校验."""
    assert AccountUpdate(cron_expr=expr).cron_expr == expr


@pytest.mark.parametrize("expr", ["hello world", "99 99 * * *", "* * * *"])
def test_account_update_rejects_invalid_cron(expr: str) -> None:
    """无法解析 / 字段数错 / 越界的 cron 应在边界即被 AccountUpdate 拒绝（N1 回归）."""
    with pytest.raises(ValidationError):
        AccountUpdate(cron_expr=expr)


@pytest.mark.parametrize("timeout", [1, 60, 180, 540])
def test_account_update_accepts_positive_execution_timeout(timeout: int) -> None:
    """区间内的正整数总超时应通过 AccountUpdate 校验."""
    assert AccountUpdate(execution_timeout=timeout).execution_timeout == timeout


@pytest.mark.parametrize("timeout", [0, -1, -180])
def test_account_update_rejects_non_positive_execution_timeout(timeout: int) -> None:
    """0 / 负数应被拒绝：不允许按账户关掉「执行无限挂起」这道兜底。"""
    with pytest.raises(ValidationError):
        AccountUpdate(execution_timeout=timeout)


@pytest.mark.parametrize("timeout", [541, 600, 3600])
def test_account_update_rejects_execution_timeout_above_worker_kill_deadline(timeout: int) -> None:
    """超过上界应被拒绝：否则多进程后端 600s 的强杀兜底会先于协作撤单触发。"""
    with pytest.raises(ValidationError):
        AccountUpdate(execution_timeout=timeout)


def test_build_error_card_includes_optional_metadata() -> None:
    card = server_utils.build_error_card("boom\ntrace", account_name="acc-1", external_ip="1.2.3.4")

    assert card["header"]["template"] == "red"  # type: ignore[index]
    first_element = card["elements"][0]  # type: ignore[index]
    assert "acc-1" in first_element["content"]  # type: ignore[index]
    assert "1.2.3.4" in first_element["content"]  # type: ignore[index]


def test_build_test_card_is_neutral_and_shares_error_card_shape() -> None:
    """联通测试卡片应与错误卡片同构（header + markdown 元素），但模板/文案中性、不含错误详情."""
    card = server_utils.build_test_card()

    assert card["header"]["template"] != "red"  # type: ignore[index]
    assert card["header"]["title"]["tag"] == "plain_text"  # type: ignore[index]
    first_element = card["elements"][0]  # type: ignore[index]
    assert first_element["tag"] == "markdown"  # type: ignore[index]
    assert "测试" in first_element["content"]  # type: ignore[index]


def test_append_error_execute_record_sanitizes_account_config() -> None:
    fake_session = _FakeWriteSession()

    record = asyncio.run(
        execution_records.append_error_execute_record(
            account_id=1,
            raw_input={"account_config": {"secret": "x"}, "symbol": "BTCUSDT"},
            msg="boom",
            session_factory=lambda: fake_session,
        )
    )

    assert fake_session.committed is True
    assert record.raw_input == {"symbol": "BTCUSDT"}
    assert record.raw_result == {"msg": "boom"}
    assert record.is_success == 0


def test_append_terminated_execute_record_persists_termination_metadata() -> None:
    fake_session = _FakeWriteSession()

    record = asyncio.run(
        execution_records.append_terminated_execute_record(
            account_id=1,
            execution_id="exec-1",
            execution_kind=ExecutionKind.CLEAR_POSITIONS,
            reason="manual stop",
            mode="graceful",
            requested_at="2026-03-22T18:00:00",
            acked_at="2026-03-22T18:00:01",
            finished_at="2026-03-22T18:00:02",
            cancel_attempted=True,
            cancel_failed_order_ids=["oid-1"],
            raw_input={"account_config": {"secret": "x"}, "symbol": "ETHUSDT"},
            raw_result={"summary": {"filled": 0}},
            session_factory=lambda: fake_session,
        )
    )

    assert fake_session.committed is True
    assert record.raw_input == {"symbol": "ETHUSDT"}
    assert record.raw_result["task_status"] == ExecutionTaskStatus.TERMINATED.value
    assert record.raw_result["execution_kind"] == ExecutionKind.CLEAR_POSITIONS.value
    assert record.raw_result["termination"]["cancel_failed_order_ids"] == ["oid-1"]


def test_trade_channel_check_records_error_when_dependency_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    appended: list[tuple[int | None, str]] = []

    async def fake_append_error_execute_record(*, account_id: int | None, msg: str, **_kwargs: object) -> object:
        appended.append((account_id, msg))
        return object()

    monkeypatch.setattr(
        channel_capabilities.importlib.util,
        "find_spec",
        lambda name: None if name == "openctp_ctp" else object(),
    )
    monkeypatch.setattr(execution_records, "append_error_execute_record", fake_append_error_execute_record)

    with pytest.raises(ValueError, match="请先安装 CTP 对应的依赖"):
        asyncio.run(server_utils.trade_channel_check(_build_account()))

    assert appended == [(1, "请先安装 CTP 对应的依赖")]

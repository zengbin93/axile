"""worker backend 入口的单元测试。"""

from __future__ import annotations

from datetime import datetime
from typing import cast

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.models.execution_result import AlgorithmResult
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import UnifiedStandardInput
from axile.executor.models.unified_output import ExecutionStatus, UnifiedStandardOutput
from axile.server.db.models import Account
from axile.server.execution.worker_backend import worker as worker_backend_entry
from axile.server.execution.worker_backend import worker_responses, worker_state
from axile.server.execution.worker_backend.protocol import WorkerBackendRequest
from tests.unit.server._execution_test_support import build_account


class _FakeWorkerExecutor:
    def __init__(self) -> None:
        self.execute_input: UnifiedStandardInput | None = None
        self.empty_kwargs: dict[str, object] = {}
        self.audit_seq = 0

    def next_audit_seq(self) -> int:
        self.audit_seq += 1
        return self.audit_seq

    def execute(
        self,
        standard_input: UnifiedStandardInput,
        *,
        cleanup: bool = True,  # noqa: FBT001, FBT002
        retain_runtime: bool = False,  # noqa: FBT001, FBT002
    ) -> UnifiedStandardOutput:
        _ = cleanup, retain_runtime
        self.execute_input = standard_input
        return UnifiedStandardOutput(
            account_assets=UnifiedAccountAssets(
                available_cash=1000.0,
                total_asset=1000.0,
                market_value=0.0,
                positions=[],
            ),
            memory={"ts": datetime(2026, 3, 27, 10, 0, 0)},
            inputs=standard_input,
            execution_time=0.1,
            channel_type=TradeChannel.GM,
            symbol_results={
                "SHSE.600000": AlgorithmResult(
                    symbol="SHSE.600000",
                    algorithm="SINGLE-MAKER",
                    status=ExecutionStatus.SUCCEEDED,
                    orders=[],
                    target_volume=100,
                    first_tick=None,
                    memory={"status": "done"},
                )
            },
            status=ExecutionStatus.SUCCEEDED,
            success=True,
        )

    def empty_positions(
        self,
        *,
        cleanup: bool = True,  # noqa: FBT001, FBT002
        retain_runtime: bool = False,  # noqa: FBT001, FBT002
        **kwargs: object,
    ) -> UnifiedStandardOutput:
        _ = cleanup, retain_runtime
        self.empty_kwargs = kwargs
        return UnifiedStandardOutput(
            account_assets=UnifiedAccountAssets(
                available_cash=900.0,
                total_asset=900.0,
                market_value=0.0,
                positions=[],
            ),
            memory={"ts": datetime(2026, 3, 27, 10, 0, 0)},
            inputs=None,
            execution_time=0.2,
            channel_type=TradeChannel.GM,
            symbol_results={},
            status=ExecutionStatus.NOOP,
            success=True,
        )


def _build_gm_account() -> Account:
    return Account(
        id=2,
        name="gm-worker-test",
        market="A股",
        trade_channel=TradeChannel.GM,
        account_control_preset="default",
        account_control_override=None,
        account_config={
            "account_id": "gm-account",
            "token": "token",
            "serv_addr": "127.0.0.1:7001",
        },
        is_started=True,
        cron_expr="* * * * *",
        remark=None,
        brokerage="gm",
        weight_precision=0.01,
        long_leverage=1.0,
        short_leverage=0.0,
        algorithm={"method": "SINGLE-MAKER", "params": {}},
        empty_positions_algorithm=None,
        trade_rules={"SHSE.600000": {"min_notional": 100.0}},
        forbidden_symbols=[],
        risk_symbols=[],
        feishu_key=None,
        portfolio_id=1,
        write_empty_record=0,
    )


def test_handle_execute_trade_returns_result_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _build_gm_account()
    fake_executor = _FakeWorkerExecutor()
    captured: dict[str, object] = {}

    monkeypatch.setattr(worker_backend_entry, "_resolve_prepared_executor", lambda **_kwargs: fake_executor)
    monkeypatch.setattr(worker_backend_entry, "_finalize_executor", lambda _executor: None)

    def fake_append_trade_pre_execute_audit(**kwargs: object) -> None:
        captured["pre_execute"] = kwargs

    def fake_append_success_audit(**kwargs: object) -> None:
        captured["success"] = kwargs

    monkeypatch.setattr(worker_backend_entry, "_append_trade_pre_execute_audit", fake_append_trade_pre_execute_audit)
    monkeypatch.setattr(worker_backend_entry, "_append_success_audit", fake_append_success_audit)

    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": TradeChannel.GM.value,
            "account_config": account.account_config,
            "curr_target": {"SHSE.600000": 0.12},
            "last_target": {},
            "algorithm": {"method": "SINGLE-MAKER", "params": {}},
            "trade_rules": account.trade_rules,
            "extra": {
                "audit": {
                    "execution_id": "exec-worker-trade-1",
                    "account_id": account.id,
                    "channel": account.trade_channel.value,
                    "algorithm": "SINGLE-MAKER",
                    "trigger_source": "manual",
                    "execution_kind": "rebalance",
                }
            },
        }
    )
    request = WorkerBackendRequest(
        request_id="req-1",
        command="execute_trade",
        account_payload=account.model_dump(mode="json"),
        execution_id="exec-worker-trade-1",
        payload={
            "standard_input": standard_input.to_dict(),
            "audit_input": {"curr_target": {"SHSE.600000": 0.12}},
            "strategy_count": 1,
            "trigger_source": "manual",
            "cleanup": True,
        },
    )

    response = worker_backend_entry._handle_execute_trade(request, worker_backend_entry._WorkerBackendState())

    assert response.kind == "result"
    assert response.output_payload is not None
    assert "inputs" not in response.output_payload
    assert UnifiedStandardOutput.model_validate(response.output_payload).inputs is None
    assert fake_executor.execute_input is not None
    assert fake_executor.execute_input.curr_target == {"SHSE.600000": 0.12}
    assert cast(dict[str, object], captured["pre_execute"])["strategy_count"] == 1
    assert cast(dict[str, object], captured["success"])["algorithm_name"] == "SINGLE-MAKER"


def test_resolve_executor_uses_factory_and_caches_non_gm_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker backend 应通过工厂创建执行器，并允许复用非 GM 渠道实例。"""
    account = build_account()
    fake_executor = _FakeWorkerExecutor()
    created: list[Account] = []
    state = worker_backend_entry._WorkerBackendState()

    def fake_create_executor_instance(factory_account: Account) -> _FakeWorkerExecutor:
        created.append(factory_account)
        return fake_executor

    monkeypatch.setattr(worker_state, "create_executor_instance", fake_create_executor_instance)

    executor_first = worker_state._resolve_executor(state, account)
    executor_second = worker_state._resolve_executor(state, account)

    assert executor_first is fake_executor
    assert executor_second is fake_executor
    assert created == [account]


def test_handle_empty_positions_returns_result_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _build_gm_account()
    fake_executor = _FakeWorkerExecutor()
    captured: dict[str, object] = {}

    monkeypatch.setattr(worker_backend_entry, "_resolve_prepared_executor", lambda **_kwargs: fake_executor)
    monkeypatch.setattr(worker_backend_entry, "_finalize_executor", lambda _executor: None)

    def fake_append_empty_positions_pre_execute_audit(**kwargs: object) -> None:
        captured["pre_execute"] = kwargs

    def fake_append_success_audit(**kwargs: object) -> None:
        captured["success"] = kwargs

    monkeypatch.setattr(
        worker_backend_entry,
        "_append_empty_positions_pre_execute_audit",
        fake_append_empty_positions_pre_execute_audit,
    )
    monkeypatch.setattr(worker_backend_entry, "_append_success_audit", fake_append_success_audit)

    request = WorkerBackendRequest(
        request_id="req-2",
        command="empty_positions",
        account_payload=account.model_dump(mode="json"),
        execution_id="exec-worker-empty-1",
        payload={
            "empty_kwargs": {
                "algorithm": {"method": "SINGLE-MAKER"},
                "feishu_key": None,
                "extra": {
                    "audit": {
                        "execution_id": "exec-worker-empty-1",
                        "account_id": account.id,
                        "channel": account.trade_channel.value,
                        "algorithm": "SINGLE-MAKER",
                        "trigger_source": "empty_positions",
                        "execution_kind": "clear_positions",
                    }
                },
            },
            "audit_input": {"algorithm": {"method": "SINGLE-MAKER"}},
        },
    )

    response = worker_backend_entry._handle_empty_positions(request, worker_backend_entry._WorkerBackendState())

    assert response.kind == "result"
    assert response.output_payload is not None
    assert fake_executor.empty_kwargs["algorithm"] == {"method": "SINGLE-MAKER"}
    assert cast(dict[str, object], captured["pre_execute"])["algorithm_name"] == "SINGLE-MAKER"
    assert cast(dict[str, object], captured["success"])["include_trade_rule_snapshots"] is False


def test_handle_execute_trade_uses_account_channel_for_standard_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker backend 应按账户渠道反序列化标准输入，而不是写死 GM。"""
    account = build_account()
    fake_executor = _FakeWorkerExecutor()

    monkeypatch.setattr(worker_backend_entry, "_resolve_prepared_executor", lambda **_kwargs: fake_executor)
    monkeypatch.setattr(worker_backend_entry, "_finalize_executor", lambda _executor: None)
    monkeypatch.setattr(worker_backend_entry, "_append_trade_pre_execute_audit", lambda **_kwargs: None)
    monkeypatch.setattr(worker_backend_entry, "_append_success_audit", lambda **_kwargs: None)

    request = WorkerBackendRequest(
        request_id="req-ctp",
        command="execute_trade",
        account_payload=account.model_dump(mode="json"),
        execution_id="exec-worker-ctp-1",
        payload={
            "standard_input": {
                "channel_type": TradeChannel.GM.value,
                "account_config": account.account_config,
                "curr_target": {"BTCUSDT": 0.1},
                "last_target": {},
                "algorithm": {"method": "SINGLE-MAKER", "params": {}},
                "trade_rules": {},
                "extra": {"audit": {"execution_id": "exec-worker-ctp-1"}},
            },
            "audit_input": {"curr_target": {"BTCUSDT": 0.1}},
            "strategy_count": 1,
            "trigger_source": "manual",
            "cleanup": True,
        },
    )

    response = worker_backend_entry._handle_execute_trade(
        request,
        worker_backend_entry._WorkerBackendState(),
    )

    assert response.kind == "result"
    assert fake_executor.execute_input is not None
    assert fake_executor.execute_input.channel_type == TradeChannel.CTP
    assert fake_executor.execute_input.account_config.channel_type == TradeChannel.CTP


def test_handle_worker_shutdown_command_returns_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shutdown 命令应返回确认响应，并清理缓存执行器。"""
    finalized: list[object | None] = []
    state = worker_backend_entry._WorkerBackendState(executor=object(), account_id=2, config_signature="sig")

    monkeypatch.setattr(worker_backend_entry, "_finalize_executor", lambda executor: finalized.append(executor))

    response = worker_backend_entry._handle_worker_request(
        WorkerBackendRequest.shutdown("req-shutdown", reason="test"),
        state,
    )

    assert response.kind == "result"
    assert response.output_payload == {"shutdown": True, "reason": "test"}
    assert len(finalized) == 1
    assert state.executor is None
    assert state.config_signature is None


def test_handle_execute_trade_exception_returns_structured_error_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execute_trade 异常应返回结构化错误响应，并写 execution_failed 审计。"""
    account = _build_gm_account()
    captured: dict[str, object] = {}

    class _BoomExecutor(_FakeWorkerExecutor):
        def execute(
            self,
            standard_input: UnifiedStandardInput,
            *,
            cleanup: bool = True,  # noqa: FBT001, FBT002
            retain_runtime: bool = False,  # noqa: FBT001, FBT002
        ) -> UnifiedStandardOutput:
            _ = standard_input, cleanup, retain_runtime
            raise RuntimeError("boom")

    monkeypatch.setattr(worker_backend_entry, "_resolve_prepared_executor", lambda **_kwargs: _BoomExecutor())
    monkeypatch.setattr(worker_backend_entry, "_finalize_executor", lambda _executor: None)
    monkeypatch.setattr(worker_backend_entry, "_append_trade_pre_execute_audit", lambda **_kwargs: None)
    monkeypatch.setattr(worker_responses.logger, "exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        worker_backend_entry,
        "_append_failed_audit",
        lambda **kwargs: captured.update(kwargs),
    )

    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": TradeChannel.GM.value,
            "account_config": account.account_config,
            "curr_target": {"SHSE.600000": 0.12},
            "last_target": {},
            "algorithm": {"method": "SINGLE-MAKER", "params": {}},
            "trade_rules": account.trade_rules,
            "extra": {"audit": {"execution_id": "exec-worker-trade-error-1"}},
        }
    )
    request = WorkerBackendRequest(
        request_id="req-error",
        command="execute_trade",
        account_payload=account.model_dump(mode="json"),
        execution_id="exec-worker-trade-error-1",
        payload={
            "standard_input": standard_input.to_dict(),
            "audit_input": {"curr_target": {"SHSE.600000": 0.12}},
            "strategy_count": 1,
            "trigger_source": "manual",
            "cleanup": True,
        },
    )

    response = worker_backend_entry._handle_execute_trade(
        request,
        worker_backend_entry._WorkerBackendState(),
    )

    assert response.kind == "error"
    assert response.error is not None
    assert response.error.type == "runtime_error"
    assert response.error.message == "boom"
    assert response.error.retryable is False
    error_payload = cast(object, captured["error"])
    assert getattr(error_payload, "type") == "runtime_error"
    assert getattr(error_payload, "message") == "boom"

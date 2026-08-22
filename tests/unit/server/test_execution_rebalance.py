"""调仓执行场景测试。"""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from axile.common.trade_channel import TradeChannel
from axile.domain.execution import ExecutionArtifactType, ExecutionEventStatus, ExecutionEventType
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import UnifiedStandardInput
from axile.executor.models.unified_output import ExecutionStatus, UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData
from axile.server.db.models import Account
from axile.server.execution import backend as execution_backend
from axile.server.execution import lifecycle as execution_lifecycle
from axile.server.execution import rebalance as rebalance_execution
from axile.server.execution import registry as execution_registry
from axile.server.execution.dispatch import ExecutionBackendKind
from tests.unit.server._execution_test_support import (
    AccountSession,
    FakeExecutor,
    FakeSession,
    FakeWorkerBackendManager,
    WarningLogger,
    build_account,
    noop_append_execution_artifact,
    noop_append_execution_event,
)


class _VolumeCalcStub:
    logger: WarningLogger

    def __init__(self, logger: WarningLogger) -> None:
        self.logger = logger

    @staticmethod
    def _calculate_generic_volume(
        weight: float,
        price: float,
        account_assets: UnifiedAccountAssets,
        _trade_rule: dict[str, object],
        *,
        symbol: str | None = None,
    ) -> float:
        del symbol
        return weight * account_assets.total_asset / price


@pytest.fixture(autouse=True)
def _keep_inline_scenarios_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文件测试编排；仅显式 GM 场景走独立 worker 测试桩。"""
    monkeypatch.setattr(
        execution_backend,
        "resolve_execution_backend_kind",
        lambda channel: ExecutionBackendKind.PROCESS if channel == TradeChannel.GM else ExecutionBackendKind.THREAD,
    )


def test_calculate_target_volume_does_not_restore_forbidden_symbols_from_last_target() -> None:
    """不应从上一次目标快照中恢复被禁止交易的品种。"""
    logger = WarningLogger()
    fake_self = cast(AbstractExecutor, cast(object, _VolumeCalcStub(logger)))
    account_assets = UnifiedAccountAssets(
        available_cash=100.0,
        total_asset=100.0,
        market_value=0.0,
        positions=[],
    )
    market_data = {
        "ADAUSDT": UnifiedPriceData(
            symbol="ADAUSDT",
            last_price=1.0,
            bid_price=1.0,
            ask_price=1.0,
            bid_volume=1.0,
            ask_volume=1.0,
            volume=1.0,
            turnover=1.0,
            timestamp=1,
            update_time="2026-03-13T00:00:00",
        )
    }

    result = AbstractExecutor.calculate_target_volume_base(
        fake_self,
        curr_target={"ADAUSDT": 0.1},
        account_assets=account_assets,
        market_data=market_data,
        trade_rules={},
        last_target={"BTCUSDT": 0.2},
        forbidden_symbols=["BTCUSDT"],
    )

    assert result == {"ADAUSDT": 10.0}
    assert logger.messages == []


def test_trade_serializes_success_result_to_json_safe_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """将成功执行结果序列化为可安全写入 JSON 的载荷。"""
    account = build_account()
    captured: dict[str, object] = {}

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        result = cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json"))
        captured["account"] = account
        captured["strategy_config"] = strategy_config
        captured["raw_input"] = raw_input
        captured["result"] = result
        captured["execution_id"] = execution_id
        return SimpleNamespace(id=101, is_success=1), result

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", lambda _account: FakeExecutor())
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(rebalance_execution.trade(account, {"ETHUSDT": 0.1}, []))

    result = captured["result"]
    assert isinstance(result, dict)
    assert result["memory"]["ts"] == "2026-03-11T21:20:13"
    assert set(result) == {
        "account_assets",
        "inputs",
        "memory",
        "status",
        "symbol_results",
        "channel_type",
        "error",
        "execution_time",
        "success",
        "extra",
    }
    assert result["symbol_results"]["ETHUSDT"]["algorithm"] == "SINGLE-MAKER"
    assert captured["execution_id"] is None


def test_trade_builds_model_before_execute_and_persists_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标准输入在进入执行器前应已转成模型，落库时仍写入字典快照。"""
    account = build_account(feishu_key="secret-feishu-key")
    fake_executor = FakeExecutor()
    captured: dict[str, object] = {}

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, output
        captured["raw_input"] = raw_input
        captured["execution_id"] = execution_id
        return (
            SimpleNamespace(id=105, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", lambda _account: fake_executor)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(rebalance_execution.trade(account, {"ETHUSDT": 0.1}, []))

    assert isinstance(fake_executor.execute_input, UnifiedStandardInput)
    assert fake_executor.execute_input.curr_target == {"ETHUSDT": 0.1}
    assert fake_executor.execute_input.feishu_key == "secret-feishu-key"

    raw_input = captured["raw_input"]
    assert isinstance(raw_input, dict)
    assert raw_input["curr_target"] == {"ETHUSDT": 0.1}
    assert raw_input["feishu_key"] == "secret-feishu-key"
    assert "account_config" in raw_input


def test_trade_defaults_gm_ashare_short_leverage_to_zero_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GM+A股 且未显式配置 short_leverage 时，应默认按 long-only 处理负目标。"""
    account = build_account(
        name="gm-ashare-account",
        market="A股",
        trade_channel=TradeChannel.GM,
        brokerage="gm",
        account_config={
            "account_id": "gm-account",
            "token": "token",
            "serv_addr": "127.0.0.1:7001",
        },
        long_leverage=None,
        short_leverage=None,
        weight_precision=0.01,
    )
    manager = FakeWorkerBackendManager()

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, raw_input, output, execution_id
        return (
            SimpleNamespace(id=108, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_backend, "get_worker_backend_manager", lambda: manager)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"SHSE.600000": 0.13, "SHSE.588000": -0.09},
            [],
        )
    )

    assert len(manager.trade_calls) == 1
    standard_input = cast(UnifiedStandardInput, manager.trade_calls[0]["standard_input"])
    assert standard_input.curr_target == {
        "SHSE.600000": 0.13,
        "SHSE.588000": 0.0,
    }


def test_trade_routes_gm_account_to_worker_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GM 调仓应走 worker manager，而不是主进程内创建执行器并写审计。"""
    account = build_account(
        name="gm-live-account",
        market="A股",
        trade_channel=TradeChannel.GM,
        brokerage="gm",
        account_config={
            "account_id": "gm-account",
            "token": "token",
            "serv_addr": "127.0.0.1:7001",
        },
    )
    manager = FakeWorkerBackendManager()
    captured: dict[str, object] = {}

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, output
        captured["raw_input"] = raw_input
        captured["execution_id"] = execution_id
        return (
            SimpleNamespace(id=205, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    def unexpected_create_executor_instance(_account: Account) -> FakeExecutor:
        raise AssertionError("GM 路径不应在主进程创建执行器")

    async def unexpected_append_execution_event(**_kwargs: object) -> bool:
        raise AssertionError("GM worker 路径不应在主进程写 execution event")

    async def unexpected_append_execution_artifact(**_kwargs: object) -> bool:
        raise AssertionError("GM worker 路径不应在主进程写 execution artifact")

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", unexpected_create_executor_instance)
    monkeypatch.setattr(execution_backend, "get_worker_backend_manager", lambda: manager)
    monkeypatch.setattr(execution_backend, "append_execution_event", unexpected_append_execution_event)
    monkeypatch.setattr(execution_backend, "append_execution_artifact", unexpected_append_execution_artifact)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"SHSE.600000": 0.12},
            [],
            execution_id="exec-gm-worker-trade-1",
            trigger_source="manual",
        )
    )

    assert len(manager.trade_calls) == 1
    trade_call = manager.trade_calls[0]
    assert cast(UnifiedStandardInput, trade_call["standard_input"]).curr_target == {"SHSE.600000": 0.12}
    assert trade_call["execution_id"] == "exec-gm-worker-trade-1"
    assert trade_call["trigger_source"] == "manual"
    assert trade_call["cleanup"] is True
    assert captured["raw_input"] == cast(dict[str, object], trade_call["standard_input_dict"])
    assert captured["execution_id"] == "exec-gm-worker-trade-1"


def test_trade_routes_ctp_account_to_worker_manager_when_policy_is_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """后端选择应由策略驱动，而不是写死 GM 渠道。"""
    account = build_account()
    manager = FakeWorkerBackendManager()

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, raw_input, output, execution_id
        return (
            SimpleNamespace(id=305, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    def unexpected_create_executor_instance(_account: Account) -> FakeExecutor:
        raise AssertionError("PROCESS 策略下不应走线程执行器")

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(
        execution_backend,
        "resolve_execution_backend_kind",
        lambda _channel: ExecutionBackendKind.PROCESS,
    )
    monkeypatch.setattr(execution_backend, "get_worker_backend_manager", lambda: manager)
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", unexpected_create_executor_instance)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"BTCUSDT": 0.12},
            [],
            execution_id="exec-ctp-worker-policy-1",
            trigger_source="manual",
        )
    )

    assert len(manager.trade_calls) == 1
    assert cast(Account, manager.trade_calls[0]["account"]).trade_channel == TradeChannel.CTP
    assert cast(UnifiedStandardInput, manager.trade_calls[0]["standard_input"]).channel_type == TradeChannel.CTP


def test_trade_persists_failed_gm_worker_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GM worker 返回失败输出时，应落 error record 并保留结构化错误。"""
    account = build_account(
        name="gm-live-account",
        market="A股",
        trade_channel=TradeChannel.GM,
        brokerage="gm",
        account_config={
            "account_id": "gm-account",
            "token": "token",
            "serv_addr": "127.0.0.1:7001",
        },
    )
    manager = FakeWorkerBackendManager(
        trade_output=UnifiedStandardOutput(
            account_assets=UnifiedAccountAssets(
                available_cash=0.0,
                total_asset=0.0,
                market_value=0.0,
                positions=[],
            ),
            memory={"message": "boom"},
            inputs=None,
            execution_time=0.0,
            channel_type=TradeChannel.GM,
            symbol_results={},
            status=ExecutionStatus.FAILED,
            error="boom",
            success=False,
            extra={
                "worker_error": {
                    "type": "runtime_error",
                    "message": "boom",
                    "retryable": False,
                }
            },
        )
    )
    captured_error_record: dict[str, object] = {}

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: UnifiedStandardOutput,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config
        raw_result = cast("dict[str, object]", output.model_dump(mode="json"))
        captured_error_record.update(
            {
                "account_id": 1,
                "strategy_config": [],
                "raw_input": raw_input,
                "raw_result": raw_result,
                "msg": output.get_error_message(),
                "execution_id": execution_id,
            }
        )
        return SimpleNamespace(id=401, is_success=0), raw_result

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_backend, "get_worker_backend_manager", lambda: manager)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    record = asyncio.run(
        rebalance_execution.trade(
            account,
            {"SHSE.600000": 0.12},
            [],
            execution_id="exec-gm-worker-error-1",
            trigger_source="manual",
        )
    )

    assert record.id == 401
    assert record.is_success == 0
    assert captured_error_record["execution_id"] == "exec-gm-worker-error-1"
    assert captured_error_record["msg"] == "boom"
    assert captured_error_record["raw_result"]["extra"]["worker_error"] == {
        "type": "runtime_error",
        "message": "boom",
        "retryable": False,
    }


def test_execute_trade_rejects_overlapping_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应拒绝同一账户发生重叠执行。"""
    account = build_account()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_execute_trade_inner(
        account_id: int,
        execution_id: str | None = None,
        trigger_source: str = "scheduler",
        _logger: object | None = None,
    ) -> SimpleNamespace:
        assert account_id == 1
        assert trigger_source == "scheduler"
        assert execution_id is not None
        started.set()
        _ = await release.wait()
        return SimpleNamespace(id=107, is_success=1)

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: AccountSession(account))
    monkeypatch.setattr(rebalance_execution, "_run_account_rebalance", fake_execute_trade_inner)

    async def runner() -> None:
        first_task = asyncio.create_task(rebalance_execution.execute_trade(1))
        _ = await started.wait()

        with pytest.raises(execution_registry.AccountExecutionAlreadyRunningError):
            _ = await rebalance_execution.execute_trade(1)

        release.set()
        await first_task

    try:
        asyncio.run(runner())
    finally:
        with execution_registry._running_account_executions_lock:
            execution_registry._running_account_executions.pop(1, None)


def test_trade_passes_execution_id_to_persisted_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应将 execution 标识透传到执行记录持久化逻辑。"""
    account = build_account()
    captured: dict[str, object] = {}

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, raw_input, output
        captured["execution_id"] = execution_id
        return (
            SimpleNamespace(id=105, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", lambda _account: FakeExecutor())
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)
    monkeypatch.setattr(execution_backend, "append_execution_event", noop_append_execution_event)
    monkeypatch.setattr(execution_backend, "append_execution_artifact", noop_append_execution_artifact)
    monkeypatch.setattr(execution_lifecycle, "append_execution_artifact", noop_append_execution_artifact)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"ETHUSDT": 0.1},
            [],
            execution_id="exec-test-1",
        )
    )

    assert captured["execution_id"] == "exec-test-1"


def test_trade_emits_execution_events_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功执行交易时，应写入 execution 事件与附件。"""
    account = build_account(trade_rules={"ETHUSDT": {"min_notional": 5.0}})
    captured_events: list[tuple[str, str]] = []
    captured_artifacts: list[str] = []
    execution_summary_content: dict[str, object] | None = None
    target_snapshot_content: dict[str, object] | None = None

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_execution_event(**kwargs: object) -> bool:
        event_type = cast(ExecutionEventType, kwargs["event_type"])
        reason_code = cast(str, kwargs["reason_code"])
        captured_events.append((event_type.value, reason_code))
        return True

    async def fake_append_execution_artifact(**kwargs: object) -> bool:
        nonlocal execution_summary_content, target_snapshot_content
        artifact_type = cast(ExecutionArtifactType, kwargs["artifact_type"])
        captured_artifacts.append(artifact_type.value)
        if artifact_type == ExecutionArtifactType.EXECUTION_SUMMARY:
            execution_summary_content = cast("dict[str, object]", kwargs["content"])
        if artifact_type == ExecutionArtifactType.TARGET_SNAPSHOT:
            target_snapshot_content = cast("dict[str, object]", kwargs["content"])
        return True

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, raw_input, output, execution_id
        return (
            SimpleNamespace(id=106, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", lambda _account: FakeExecutor())
    monkeypatch.setattr(execution_backend, "append_execution_event", fake_append_execution_event)
    monkeypatch.setattr(execution_backend, "append_execution_artifact", fake_append_execution_artifact)
    monkeypatch.setattr(execution_lifecycle, "append_execution_artifact", fake_append_execution_artifact)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"ETHUSDT": 0.1},
            [],
            execution_id="exec-audit-1",
            trigger_source="manual",
            target_update_time="2026-07-02T09:00:00",
        )
    )

    assert captured_events[0][0] == "execution_started"
    assert ("input_snapshotted", "COMMON.INPUT_SNAPSHOTTED") in captured_events
    assert ("target_computed", "COMMON.TARGET_COMPUTED") in captured_events
    assert captured_events[-1] == ("execution_completed", "COMMON.EXECUTION_COMPLETED")
    assert "standard_input" in captured_artifacts
    assert "target_snapshot" in captured_artifacts
    assert "trade_rules_snapshot" in captured_artifacts
    assert "account_snapshot_before" in captured_artifacts
    assert "account_snapshot" in captured_artifacts
    assert "execution_summary" in captured_artifacts
    assert execution_summary_content is not None
    assert execution_summary_content["summary"] == {
        "symbols_total": 1,
        "symbols_succeeded": 1,
        "symbols_failed": 0,
        "symbols_noop": 0,
    }
    assert execution_summary_content["success"] is True
    assert execution_summary_content["execution_time"] == 0.1
    reconciliation = cast("dict[str, object]", execution_summary_content["reconciliation"])
    account_block = cast("dict[str, object]", reconciliation["account"])
    assert account_block["source_before"] == "real"
    assert account_block["equity_before"] == 1000.0
    symbols = cast("list[dict[str, object]]", reconciliation["symbols"])
    eth_row = next(row for row in symbols if row["symbol"] == "ETHUSDT")
    assert eth_row["target"] == 0.1
    assert eth_row["after"] == 0.0
    assert eth_row["reached"] is False
    # target_update_time 应随 extra 一路透传进 TARGET_SNAPSHOT。
    assert target_snapshot_content is not None
    assert target_snapshot_content["target_update_time"] == "2026-07-02T09:00:00"


def test_trade_prepares_execution_runtime_before_pre_execute_audit_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务端应在 pre-execute 审计事件前准备 runtime，并与 execute 内部继续共用同一序列。"""
    account = build_account()
    fake_executor: object | None = None
    captured_event_seqs: list[int] = []

    class _RuntimeAwareExecutor(FakeExecutor):
        prepared = False
        prepare_calls = 0
        execute_seq: int | None = None

        def prepare_execution_runtime(self) -> object:
            self.prepared = True
            self.prepare_calls += 1
            return object()

        def next_audit_seq(self) -> int:
            assert self.prepared is True
            return super().next_audit_seq()

        def execute(
            self,
            _standard_input: object,
            cleanup: bool = True,  # noqa: FBT002
            retain_runtime: bool = False,  # noqa: FBT001, FBT002
        ) -> UnifiedStandardOutput:
            _ = retain_runtime
            self.execute_seq = self.next_audit_seq()
            return super().execute(_standard_input, cleanup=cleanup)

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_execution_event(**kwargs: object) -> bool:
        captured_event_seqs.append(cast(int, kwargs["seq"]))
        return True

    async def fake_append_execution_artifact(**kwargs: object) -> bool:
        _ = kwargs
        return True

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, raw_input, output, execution_id
        return (
            SimpleNamespace(id=107, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )

    def fake_create_executor_instance(_account: Account) -> _RuntimeAwareExecutor:
        nonlocal fake_executor
        fake_executor = _RuntimeAwareExecutor()
        return fake_executor

    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", fake_create_executor_instance)
    monkeypatch.setattr(execution_backend, "append_execution_event", fake_append_execution_event)
    monkeypatch.setattr(execution_backend, "append_execution_artifact", fake_append_execution_artifact)
    monkeypatch.setattr(execution_lifecycle, "append_execution_artifact", fake_append_execution_artifact)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"ETHUSDT": 0.1},
            [],
            execution_id="exec-runtime-seq-1",
            trigger_source="manual",
        )
    )

    assert fake_executor is not None
    assert fake_executor.prepare_calls == 1
    assert fake_executor.execute_seq == 4
    assert captured_event_seqs == [1, 2, 3, 5]


@pytest.mark.parametrize(
    ("output_status", "error_message", "expected_event_status"),
    [
        (ExecutionStatus.BLOCKED, "当前不在交易时间", ExecutionEventStatus.WARNING),
        (ExecutionStatus.FAILED, "执行失败", ExecutionEventStatus.ERROR),
    ],
)
def test_trade_persists_unsuccessful_output_without_marking_success(
    monkeypatch: pytest.MonkeyPatch,
    output_status: ExecutionStatus,
    error_message: str,
    expected_event_status: ExecutionEventStatus,
) -> None:
    """非成功输出不应落成 success=1，execution_completed 状态也要与结果对齐。"""
    account = build_account()
    captured_events: list[dict[str, object]] = []
    captured_error_record: dict[str, object] = {}

    class _UnsuccessfulExecutor(FakeExecutor):
        def execute(
            self,
            _standard_input: object,
            cleanup: bool = True,  # noqa: FBT002
            retain_runtime: bool = False,  # noqa: FBT001, FBT002
        ) -> UnifiedStandardOutput:
            _ = retain_runtime
            self.execute_input = _standard_input
            self.cleanup = cleanup
            return UnifiedStandardOutput(
                account_assets=UnifiedAccountAssets(
                    available_cash=1000.0,
                    total_asset=1000.0,
                    market_value=0.0,
                    positions=[],
                ),
                memory={"message": error_message},
                inputs=None,
                execution_time=0.1,
                channel_type=TradeChannel.CTP,
                symbol_results={},
                status=output_status,
                error=error_message,
                success=False,
            )

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_execution_event(**kwargs: object) -> bool:
        captured_events.append(dict(kwargs))
        return True

    async def fake_append_execution_artifact(**_kwargs: object) -> bool:
        return True

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: UnifiedStandardOutput,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config
        raw_result = cast("dict[str, object]", output.model_dump(mode="json"))
        captured_error_record.update(
            {
                "account_id": 1,
                "raw_input": raw_input,
                "raw_result": raw_result,
                "msg": output.get_error_message(),
                "execution_id": execution_id,
            }
        )
        return SimpleNamespace(id=301, is_success=0), raw_result

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", lambda _account: _UnsuccessfulExecutor())
    monkeypatch.setattr(execution_backend, "append_execution_event", fake_append_execution_event)
    monkeypatch.setattr(execution_backend, "append_execution_artifact", fake_append_execution_artifact)
    monkeypatch.setattr(execution_lifecycle, "append_execution_artifact", fake_append_execution_artifact)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)

    record = asyncio.run(
        rebalance_execution.trade(
            account,
            {"ETHUSDT": 0.1},
            [],
            execution_id="exec-unsuccessful-1",
            trigger_source="manual",
        )
    )

    assert record.id == 301
    assert record.is_success == 0
    assert captured_error_record["account_id"] == 1
    assert captured_error_record["execution_id"] == "exec-unsuccessful-1"
    assert captured_error_record["msg"] == error_message
    assert captured_error_record["raw_result"]["status"] == output_status.value
    assert captured_events[-1]["event_type"] == ExecutionEventType.EXECUTION_COMPLETED
    assert captured_events[-1]["status"] == expected_event_status
    assert captured_events[-1]["details"] == {
        "debug": {
            "record_id": 301,
            "success": False,
            "execution_status": output_status.value,
        },
        "order": {
            "orders_count": 0,
        },
    }


def test_trade_binds_account_control_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rebalance 入口应绑定账户控制防护层。"""
    account = build_account()
    fake_executor = FakeExecutor()
    fake_guard = object()
    captured: dict[str, object] = {}

    async def fake_get_latest_success_execute_record_by_account_id(_session: object, _account_id: int) -> None:
        return None

    async def fake_append_output_record(
        *,
        account: object,
        strategy_config: object,
        raw_input: object,
        output: object,
        execution_id: str | None = None,
        execution_kind: object = None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        _ = account, strategy_config, raw_input, output, execution_id
        return (
            SimpleNamespace(id=201, is_success=1),
            cast("dict[str, object]", cast(UnifiedStandardOutput, output).model_dump(mode="json")),
        )

    async def fake_build_account_control_guard(_account: Account, execution_id: str | None) -> object:
        captured["account_id"] = _account.id
        captured["channel"] = _account.trade_channel
        captured["execution_id"] = execution_id
        return fake_guard

    monkeypatch.setattr(rebalance_execution, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        rebalance_execution,
        "get_latest_success_execute_record_by_account_id",
        fake_get_latest_success_execute_record_by_account_id,
    )
    monkeypatch.setattr(execution_lifecycle, "create_executor_instance", lambda _account: fake_executor)
    monkeypatch.setattr(execution_backend, "_append_output_record", fake_append_output_record)
    monkeypatch.setattr(execution_lifecycle, "build_account_control_guard", fake_build_account_control_guard)
    monkeypatch.setattr(execution_backend, "append_execution_event", noop_append_execution_event)
    monkeypatch.setattr(execution_backend, "append_execution_artifact", noop_append_execution_artifact)
    monkeypatch.setattr(execution_lifecycle, "append_execution_artifact", noop_append_execution_artifact)

    _ = asyncio.run(
        rebalance_execution.trade(
            account,
            {"ETHUSDT": 0.1},
            [],
            execution_id="exec-bind-1",
        )
    )

    assert captured == {
        "account_id": 1,
        "channel": TradeChannel.CTP,
        "execution_id": "exec-bind-1",
    }
    assert fake_executor.account_control_guard is fake_guard


def test_target_update_time_survives_standard_input_serialization() -> None:
    """target_update_time 应经 to_dict/from_dict 往返仍保留在 extra 中。

    worker 后端在独立进程重建 UnifiedStandardInput，只能读到序列化过的 extra，
    该测试直接验证跨进程通道不会丢失 target_update_time。
    """
    account = build_account()

    standard_input = rebalance_execution._build_rebalance_standard_input(
        account=account,
        curr_target={"ETHUSDT": 0.1},
        last_target={},
        execution_id="exec-roundtrip-1",
        trigger_source="scheduler",
        target_update_time="2026-07-02T09:00:00",
    )
    assert standard_input.extra["target_update_time"] == "2026-07-02T09:00:00"

    restored = UnifiedStandardInput.from_dict(standard_input.to_dict())
    assert restored.extra.get("target_update_time") == "2026-07-02T09:00:00"


def test_standard_input_accepts_database_trade_channel_string() -> None:
    """Text 列读回普通 str 时，调仓输入仍应能正常构造。"""
    account = build_account(
        account_config={"account_id": "gm-account", "token": "token", "serv_addr": "127.0.0.1:7001"}
    )
    account.trade_channel = cast("TradeChannel", "gm")

    standard_input = rebalance_execution._build_rebalance_standard_input(
        account=account,
        curr_target={"SHSE.600000": 0.1},
        last_target={},
        execution_id="exec-db-channel-1",
        trigger_source="scheduler",
    )

    assert standard_input.channel_type == TradeChannel.GM
    assert cast("dict[str, object]", standard_input.extra["audit"])["channel"] == "gm"


def test_target_update_time_defaults_to_none_when_absent() -> None:
    """未提供 target_update_time 时，extra 中该键为 None 且往返保持 None。"""
    account = build_account()

    standard_input = rebalance_execution._build_rebalance_standard_input(
        account=account,
        curr_target={"ETHUSDT": 0.1},
        last_target={},
        execution_id="exec-roundtrip-2",
        trigger_source="scheduler",
    )
    assert standard_input.extra["target_update_time"] is None

    restored = UnifiedStandardInput.from_dict(standard_input.to_dict())
    assert restored.extra.get("target_update_time") is None


def test_account_execution_timeout_flows_into_standard_input() -> None:
    """账户上配置的执行总超时必须进入标准输入，并经跨进程序列化往返保留。"""
    account = build_account(execution_timeout=45)

    standard_input = rebalance_execution._build_rebalance_standard_input(
        account=account,
        curr_target={"ETHUSDT": 0.1},
        last_target={},
        execution_id="exec-timeout-1",
        trigger_source="scheduler",
    )
    assert standard_input.execution_timeout == 45

    # worker 后端在独立进程用 from_dict 重建输入，deadline 必须一起过去。
    restored = UnifiedStandardInput.from_dict(standard_input.to_dict())
    assert restored.execution_timeout == 45


def test_standard_input_execution_timeout_defaults_to_180() -> None:
    """未显式提供时，标准输入的总超时应回落到 180 秒的默认额度。"""
    payload: dict[str, object] = {
        "channel_type": TradeChannel.CTP.value,
        "account_config": {"broker_id": "9999", "investor_id": "test", "password": "test"},
        "curr_target": {},
        "last_target": {},
    }

    assert UnifiedStandardInput.from_dict(dict(payload)).execution_timeout == 180
    # 0 表示显式关闭 deadline（仿真路径依赖该语义），不能被默认值覆盖。
    assert UnifiedStandardInput.from_dict({**payload, "execution_timeout": 0}).execution_timeout == 0

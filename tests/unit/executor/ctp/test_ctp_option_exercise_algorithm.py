"""``CTP_OPTION_EXERCISE`` 算法单测.

不联机：通过 stub executor 模拟 ``submit_option_action`` 与
``get_option_action_status`` 的状态机，覆盖:

- 行权 / 放弃 / 自对冲三类 action 的 happy path
- 行权前的内在价值检查（is_exercise_valuable）
- 提交前 target_volume <= 0 的快速跳过
- 算法层对 RuntimeError / ValueError 的捕获
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from axile.executor.algorithms.core.base import AlgorithmInput
from axile.executor.algorithms.defaults.ctp_option_exercise.impl import (
    CTPOptionExerciseParams,
    ctp_option_exercise_algorithm,
)
from axile.executor.ctp.core.option_action import (
    OptionActionRecord,
    OptionActionStatus,
    OptionActionType,
)
from axile.executor.models.execution_result import ExecutionStatus


class _StubExecutor:
    """最小 ExecutorProtocol-like 桩件。"""

    def __init__(
        self,
        *,
        valuable: bool = True,
        final_status: OptionActionStatus = OptionActionStatus.EXECUTED,
        submit_raises: BaseException | None = None,
    ) -> None:
        self.logger = MagicMock()
        self._valuable = valuable
        self._final_status = final_status
        self._submit_raises = submit_raises
        self._record: OptionActionRecord | None = None

    @property
    def channel_type(self) -> Any:
        return None

    @property
    def symbol(self) -> str:
        return ""

    def is_termination_requested(self) -> bool:
        return False

    def handle_termination_checkpoint(self) -> None:
        return None

    def is_exercise_valuable(self, _symbol: str) -> bool:
        return self._valuable

    def submit_option_action(
        self,
        *,
        symbol: str,
        action: str,
        volume: int,
        trade_rule: dict[str, object] | None = None,
    ) -> OptionActionRecord:
        del trade_rule
        if self._submit_raises is not None:
            raise self._submit_raises

        self._record = OptionActionRecord(
            order_ref="42",
            instrument_id=symbol,
            action=OptionActionType(action),
            volume=volume,
            status=self._final_status,
        )
        return self._record

    def get_option_action_status(self, order_ref: str) -> OptionActionRecord | None:
        return self._record if self._record and self._record.order_ref == order_ref else None


def _make_input(
    target_volume: int = 5,
    *,
    action: str = "exercise",
    require_value_check: bool = True,
    max_wait_seconds: int = 1,
) -> AlgorithmInput:
    return AlgorithmInput(
        symbol="m2510-C-3000",
        target_volume=target_volume,
        trade_rule={"sizing_mode": "lots"},
        params=CTPOptionExerciseParams(
            action=action,
            require_value_check=require_value_check,
            max_wait_seconds=max_wait_seconds,
            poll_interval_seconds=0.0,
        ),
    )


class TestHappyPath:
    def test_exercise_executed(self) -> None:
        executor = _StubExecutor(final_status=OptionActionStatus.EXECUTED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise"))
        assert result.status == ExecutionStatus.SUCCEEDED
        assert result.error is None
        assert result.memory["option_action"]["final_status"] == "executed"

    def test_abandon_terminal_succeeded(self) -> None:
        executor = _StubExecutor(final_status=OptionActionStatus.ABANDONED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="abandon"))
        assert result.status == ExecutionStatus.SUCCEEDED
        assert result.memory["option_action"]["action"] == "abandon"

    def test_self_close_succeeded(self) -> None:
        executor = _StubExecutor(final_status=OptionActionStatus.EXECUTED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="self_close"))
        assert result.status == ExecutionStatus.SUCCEEDED


class TestValueCheck:
    def test_skip_when_not_valuable(self) -> None:
        executor = _StubExecutor(valuable=False)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise"))
        assert result.status == ExecutionStatus.NOOP
        assert result.error == "期权无内在价值，已跳过行权"

    def test_force_exercise_when_check_disabled(self) -> None:
        executor = _StubExecutor(valuable=False, final_status=OptionActionStatus.EXECUTED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise", require_value_check=False))
        assert result.status == ExecutionStatus.SUCCEEDED

    def test_value_check_skipped_for_abandon(self) -> None:
        executor = _StubExecutor(valuable=False, final_status=OptionActionStatus.ABANDONED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="abandon"))
        # 放弃指令不做内在价值检查，应直接走提交流程
        assert result.status == ExecutionStatus.SUCCEEDED


class TestEdgeCases:
    def test_zero_target_volume_returns_noop(self) -> None:
        executor = _StubExecutor()
        result = ctp_option_exercise_algorithm(executor, _make_input(target_volume=0))
        assert result.status == ExecutionStatus.NOOP

    def test_submit_raises_runtime_error(self) -> None:
        executor = _StubExecutor(submit_raises=RuntimeError("CTP 未连接"))
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise"))
        assert result.status == ExecutionStatus.FAILED
        assert "CTP 未连接" in (result.error or "")

    def test_submit_raises_value_error(self) -> None:
        executor = _StubExecutor(submit_raises=ValueError("非法 action"))
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise"))
        assert result.status == ExecutionStatus.FAILED


class TestFinalStatusMapping:
    def test_failed_terminal_maps_to_failed(self) -> None:
        executor = _StubExecutor(final_status=OptionActionStatus.FAILED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise"))
        assert result.status == ExecutionStatus.FAILED
        assert result.memory["option_action"]["final_status"] == "failed"

    def test_cancelled_terminal_maps_to_failed(self) -> None:
        executor = _StubExecutor(final_status=OptionActionStatus.CANCELLED)
        result = ctp_option_exercise_algorithm(executor, _make_input(action="exercise"))
        assert result.status == ExecutionStatus.FAILED


class TestParamsParsing:
    def test_resolve_params_from_dict(self) -> None:
        from axile.executor.algorithms.defaults.ctp_option_exercise.impl import _resolve_params

        params = _resolve_params({"action": "abandon", "max_wait_seconds": 30})
        assert isinstance(params, CTPOptionExerciseParams)
        assert params.action == "abandon"
        assert params.max_wait_seconds == 30

    def test_resolve_params_default(self) -> None:
        from axile.executor.algorithms.defaults.ctp_option_exercise.impl import _resolve_params

        params = _resolve_params(None)
        assert params.action == "exercise"
        assert params.require_value_check is True

    def test_resolve_params_invalid_type_raises(self) -> None:
        from axile.executor.algorithms.defaults.ctp_option_exercise.impl import _resolve_params

        with pytest.raises(TypeError):
            _resolve_params(123)

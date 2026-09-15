"""期权指令的取消、拒绝与未知回报不混为过程错误。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from axile.executor.algorithms.core.base import AlgorithmInput
from axile.executor.algorithms.defaults.ctp_option_exercise import impl
from axile.executor.ctp.ctp_execute import CtpSessionRecoveryRequired
from axile.executor.termination import ExecutionTerminated


@pytest.mark.parametrize(
    "status,outcome",
    [
        ("executed", "SUCCEEDED"),
        ("abandoned", "SUCCEEDED"),
        ("cancelled", "FAILED"),
        ("failed", "FAILED"),
        ("submitted", "FAILED"),
        (None, "FAILED"),
    ],
)
def test_option_action_conclusion_uses_actual_terminal_reason(monkeypatch, status, outcome):
    executor = MagicMock()
    executor.submit_option_action.return_value = SimpleNamespace(order_ref="1")
    final = SimpleNamespace(status=status, error_msg="", error_id=0) if status else None
    monkeypatch.setattr(impl, "_wait_for_terminal", lambda *args, **kwargs: final)
    result = impl.ctp_option_exercise_algorithm(
        executor,
        AlgorithmInput(
            symbol="m2701-C-3000",
            target_volume=1,
            trade_rule={},
            params=impl.CTPOptionExerciseParams(require_value_check=False),
        ),
    )
    assert result.status.value == outcome


@pytest.mark.parametrize("target,outcome", [(1, "BLOCKED"), (0, "NOOP")])
def test_value_check_skip_does_not_claim_requested_exercise_completed(target, outcome):
    executor = MagicMock()
    executor.is_exercise_valuable.return_value = False
    result = impl.ctp_option_exercise_algorithm(
        executor,
        AlgorithmInput(
            symbol="m2701-C-3000",
            target_volume=target,
            trade_rule={},
            params=impl.CTPOptionExerciseParams(),
        ),
    )
    assert result.status.value == outcome
    if target:
        assert result.error == "期权无内在价值，已跳过行权"
    executor.submit_option_action.assert_not_called()


@pytest.mark.parametrize(
    "error", [ExecutionTerminated(reason="stop", mode="cancel_pending"), CtpSessionRecoveryRequired("reconnect")]
)
def test_option_submission_propagates_termination_and_session_recovery(error):
    executor = MagicMock()
    executor.submit_option_action.side_effect = error
    with pytest.raises(type(error)) as raised:
        impl.ctp_option_exercise_algorithm(
            executor,
            AlgorithmInput(
                symbol="m2701-C-3000",
                target_volume=1,
                trade_rule={},
                params=impl.CTPOptionExerciseParams(require_value_check=False),
            ),
        )
    assert raised.value is error

"""自定义组合函数执行与返回契约测试."""

from __future__ import annotations

import asyncio

import pytest

from axile.server import portfolio_targets
from axile.server.context import build_sample_context
from axile.server.execution.worker_backend import manager as worker_manager_module
from axile.server.portfolio_runner import calculate_sample_portfolio
from axile.server.portfolio_targets import PortfolioFunctionResult, calculate_portfolio_target
from tests.unit.server._execution_test_support import build_account


def _calculate(code: str) -> PortfolioFunctionResult:
    return calculate_portfolio_target(code, build_sample_context())


def test_function_runs_in_normal_python_environment() -> None:
    result = _calculate(
        "import math\ndef calculate_portfolio(context):\n    return {'rb2610': math.sqrt(context.get_price('rb2610')) / 10}\n"
    )
    assert result.ok
    assert result.target == {"rb2610": 1.0}


def test_function_can_use_sample_account() -> None:
    result = _calculate("def calculate_portfolio(context):\n    return {'cash': context.account.available_cash}\n")
    assert result.target == {"cash": 800_000.0}


@pytest.mark.parametrize(
    ("code", "error_type", "line"),
    [
        ("def calculate_portfolio(context)\n    return {}\n", "SyntaxError", 1),
        ("portfolio = {}\n", "ValueError", None),
        ("def calculate_portfolio():\n    return {}\n", "TypeError", None),
        ("def calculate_portfolio(context):\n    raise RuntimeError('boom')\n", "RuntimeError", 2),
    ],
)
def test_function_errors_are_structured(code: str, error_type: str, line: int | None) -> None:
    result = _calculate(code)
    assert not result.ok
    assert result.error is not None
    assert result.error.error_type == error_type
    assert result.error.error_line == line
    assert result.error.formatted_traceback


@pytest.mark.parametrize(
    ("expression", "error_type"),
    [
        ("[]", "TypeError"),
        ("{1: 0.5}", "TypeError"),
        ("{'x': True}", "TypeError"),
        ("{'x': float('nan')}", "ValueError"),
        ("{'x': float('inf')}", "ValueError"),
    ],
)
def test_invalid_target_is_rejected(expression: str, error_type: str) -> None:
    result = _calculate(f"def calculate_portfolio(context):\n    return {expression}\n")
    assert not result.ok
    assert result.error is not None
    assert result.error.error_type == error_type


def test_result_payload_round_trip() -> None:
    result = _calculate("def calculate_portfolio(context):\n    return {'x': 0.25}\n")
    restored = PortfolioFunctionResult.from_payload(result.to_payload())
    assert restored.ok
    assert restored.target == {"x": 0.25}


def test_sample_runner_executes_in_disposable_process() -> None:
    result = calculate_sample_portfolio(
        "import os\ndef calculate_portfolio(context):\n    return {'pid': float(os.getpid())}\n"
    )
    assert result.ok
    assert result.target is not None
    assert result.target["pid"] != float(__import__("os").getpid())


def test_sample_runner_terminates_infinite_loop() -> None:
    result = calculate_sample_portfolio(
        "def calculate_portfolio(context):\n    while True:\n        pass\n",
        timeout=0.2,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.error_type == "TimeoutError"


def test_sample_runner_survives_child_os_exit() -> None:
    result = calculate_sample_portfolio(
        "import os\ndef calculate_portfolio(context):\n    os._exit(7)\n",
        timeout=2.0,
    )
    assert not result.ok
    assert result.error is not None
    assert "exitcode=7" in result.error.error_message


def test_real_account_always_delegates_to_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    account = build_account(id=2, trade_channel="plugin-thread")
    expected = PortfolioFunctionResult(ok=True, target={"x": 1.0})

    class _Manager:
        async def calculate_portfolio(self, actual_account, code: str, *, execution_id: str | None = None):
            assert actual_account is account
            assert code == "code"
            assert execution_id == "exec-1"
            return expected

    monkeypatch.setattr(worker_manager_module, "get_worker_backend_manager", lambda: _Manager())
    result = asyncio.run(portfolio_targets.calculate_portfolio_for_account(account, "code", execution_id="exec-1"))
    assert result is expected

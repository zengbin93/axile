"""算法参数校验失败不再被静默吞成 dict 的测试。"""

from __future__ import annotations

import pytest

from axile.executor.models.unified_input import UnifiedStandardInput
from axile.executor.models.unified_input_support import (
    AlgorithmParamsError,
    _parse_algorithm_params_with_metadata,
)


def test_parse_raises_on_invalid_params() -> None:
    """存在参数模型却校验失败时应抛出 AlgorithmParamsError，而非返回原 dict。"""
    with pytest.raises(AlgorithmParamsError) as excinfo:
        _parse_algorithm_params_with_metadata(
            {"method": "SINGLE-MAKER", "params": {"max_wait_seconds": 0}},
            "SINGLE-MAKER",
        )
    assert "SINGLE-MAKER" in str(excinfo.value)


def test_parse_returns_model_on_valid_params() -> None:
    """合法参数应解析为参数模型实例。"""
    resolved = _parse_algorithm_params_with_metadata(
        {"method": "SINGLE-MAKER", "params": {"max_wait_seconds": 3600, "chase_enabled": True, "max_chase_count": 50}},
        "SINGLE-MAKER",
    )
    params = resolved["params"]
    assert type(params).__name__ == "SingleMakerParams"
    assert params.max_wait_seconds == 3600  # type: ignore[attr-defined]


def test_parse_is_lenient_for_unknown_algorithm() -> None:
    """未注册算法无参数模型可用时，保持宽松原样返回。"""
    resolved = _parse_algorithm_params_with_metadata(
        {"method": "NO-SUCH-ALGO", "params": {"whatever": 1}},
        "NO-SUCH-ALGO",
    )
    assert resolved["params"] == {"whatever": 1}


def test_get_resolved_symbol_algorithm_raises_on_invalid_params() -> None:
    """经由统一输入解析同一路径时，非法参数同样应抛出。"""
    standard_input = UnifiedStandardInput.from_dict(
        {
            "channel_type": "ctp",
            "account_config": {
                "broker_id": "9999",
                "investor_id": "test",
                "password": "test",
                "td_front": "tcp://td:1",
                "md_front": "tcp://md:2",
                "app_id": "app",
                "auth_code": "auth",
            },
            "curr_target": {"rb2610": 0.1},
            "algorithm": {
                "method": "SINGLE-MAKER",
                "params": {"max_wait_seconds": 0, "chase_enabled": True, "max_chase_count": 99},
            },
        }
    )
    with pytest.raises(AlgorithmParamsError):
        standard_input.get_resolved_symbol_algorithm("rb2610")

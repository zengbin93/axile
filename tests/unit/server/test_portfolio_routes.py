"""自定义函数组合路由契约测试。"""

import pytest
from pydantic import ValidationError

from axile.server.api.routes.portfolio import _ensure_weight_mapping
from axile.server.db.models import PortfolioCreate, PortfolioUpdate

CODE = "def calculate_portfolio(context):\n    return {'rb2610': 1.0}\n"


def test_create_requires_non_empty_custom_function() -> None:
    with pytest.raises(ValidationError):
        PortfolioCreate(name="demo", market="crypto", custom_calc_py_code="   ")


def test_create_rejects_removed_strategy_fields() -> None:
    with pytest.raises(ValidationError):
        PortfolioCreate.model_validate(
            {
                "name": "demo",
                "market": "crypto",
                "custom_calc_py_code": CODE,
                "strategy_config": [],
            }
        )


def test_update_rejects_null_or_blank_custom_function() -> None:
    with pytest.raises(ValidationError):
        PortfolioUpdate(custom_calc_py_code=None)
    with pytest.raises(ValidationError):
        PortfolioUpdate(custom_calc_py_code="\n")


@pytest.mark.parametrize(
    "target",
    [[], {1: 0.5}, {"rb2610": True}, {"rb2610": "0.5"}, {"rb2610": float("inf")}],
)
def test_target_must_be_finite_symbol_weight_mapping(target: object) -> None:
    with pytest.raises(ValueError):
        _ensure_weight_mapping(target)


def test_target_accepts_numeric_weights() -> None:
    _ensure_weight_mapping({"rb2610": 1, "ag2612": -0.25})

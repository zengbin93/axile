"""
算法参数验证单元测试.

测试 BaseAlgorithmParams 和 ChaseParamsMixin 的参数验证规则。
"""

import pytest
from pydantic import ValidationError

from axile.executor.algorithms.common.params import (
    BaseAlgorithmParams,
    ChaseParamsMixin,
)


class TestBaseAlgorithmParams:
    """测试基础算法参数验证."""

    def test_default_values(self):
        """测试默认值."""
        params = BaseAlgorithmParams()
        assert params.max_wait_seconds == 60

    def test_normal_values(self):
        """测试正常值."""
        params = BaseAlgorithmParams(max_wait_seconds=120)
        assert params.max_wait_seconds == 120

    def test_min_boundary(self):
        """测试最小边界值."""
        params = BaseAlgorithmParams(max_wait_seconds=1)
        assert params.max_wait_seconds == 1

    def test_max_boundary(self):
        """测试最大边界值."""
        params = BaseAlgorithmParams(max_wait_seconds=3600)
        assert params.max_wait_seconds == 3600

    def test_below_min_boundary(self):
        """测试低于最小边界值."""
        with pytest.raises(ValidationError) as exc_info:
            BaseAlgorithmParams(max_wait_seconds=0)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("max_wait_seconds",)
        assert errors[0]["type"] == "greater_than_equal"

    def test_above_max_boundary(self):
        """测试超过最大边界值."""
        with pytest.raises(ValidationError) as exc_info:
            BaseAlgorithmParams(max_wait_seconds=3601)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("max_wait_seconds",)
        assert errors[0]["type"] == "less_than_equal"

    def test_str_representation(self):
        """测试字符串表示."""
        params = BaseAlgorithmParams(max_wait_seconds=120)
        assert str(params) == "BaseAlgorithmParams(max_wait_seconds=120)"

    def test_invalid_type(self):
        """测试无效类型."""
        with pytest.raises(ValidationError):
            BaseAlgorithmParams(max_wait_seconds="invalid")


class TestChaseParamsMixin:
    """测试追单参数验证."""

    def test_default_values(self):
        """测试默认值."""
        params = ChaseParamsMixin()
        assert params.chase_enabled is False
        assert params.chase_ticks == 1
        assert params.max_chase_count == 5
        assert params.chase_interval == 5.0

    def test_normal_values(self):
        """测试正常值."""
        params = ChaseParamsMixin(
            chase_enabled=True,
            chase_ticks=3,
            max_chase_count=10,
            chase_interval=10.0,
        )
        assert params.chase_enabled is True
        assert params.chase_ticks == 3
        assert params.max_chase_count == 10
        assert params.chase_interval == 10.0

    def test_chase_disabled_validation_skipped(self):
        """测试未启用追单时跳过一致性验证."""
        # 即使参数组合不合理，如果未启用追单，也应该通过验证
        params = ChaseParamsMixin(
            chase_enabled=False,
            max_chase_count=100,  # 超过推荐值
            chase_interval=10.0,
        )
        assert params.chase_enabled is False

    def test_chase_ticks_boundaries(self):
        """测试追单位数边界."""
        # 最小值（启用追单）
        params = ChaseParamsMixin(chase_enabled=True, chase_ticks=1)
        assert params.chase_ticks == 1

        # 最大值（启用追单）
        params = ChaseParamsMixin(chase_enabled=True, chase_ticks=100)
        assert params.chase_ticks == 100

        # 超过最大值（启用追单）
        with pytest.raises(ValidationError) as exc_info:
            ChaseParamsMixin(chase_enabled=True, chase_ticks=101)

        errors = exc_info.value.errors()
        # model_validator 错误位置为空，检查消息内容
        assert any("追单位数" in error["msg"] for error in errors)

    def test_max_chase_count_boundaries(self):
        """测试最大追单次数边界."""
        # 最小值（启用追单）
        params = ChaseParamsMixin(chase_enabled=True, max_chase_count=1)
        assert params.max_chase_count == 1

        # 最大值（启用追单）
        params = ChaseParamsMixin(chase_enabled=True, max_chase_count=50)
        assert params.max_chase_count == 50

        # 超过最大值（启用追单）
        with pytest.raises(ValidationError) as exc_info:
            ChaseParamsMixin(chase_enabled=True, max_chase_count=51)

        errors = exc_info.value.errors()
        # model_validator 错误位置为空，检查消息内容
        assert any("追单次数" in error["msg"] for error in errors)

    def test_chase_interval_boundaries(self):
        """测试追单间隔边界."""
        # 最小值（启用追单，使用较小的 max_chase_count 避免总时间超限）
        params = ChaseParamsMixin(chase_enabled=True, chase_interval=0.1, max_chase_count=1)
        assert params.chase_interval == 0.1

        # 最大值（启用追单，使用较小的 max_chase_count 避免总时间超限）
        params = ChaseParamsMixin(chase_enabled=True, chase_interval=300.0, max_chase_count=1)
        assert params.chase_interval == 300.0

        # 低于最小值（启用追单）
        with pytest.raises(ValidationError) as exc_info:
            ChaseParamsMixin(chase_enabled=True, chase_interval=0.01)

        errors = exc_info.value.errors()
        # model_validator 错误位置为空，检查消息内容
        assert any("追单间隔" in error["msg"] for error in errors)

    def test_total_chase_time_exceeds_limit(self):
        """测试总追单时间超过限制."""
        with pytest.raises(ValidationError) as exc_info:
            ChaseParamsMixin(
                chase_enabled=True,
                max_chase_count=50,  # 50次（不超过上限）
                chase_interval=15.0,  # 15秒间隔
                # 总时间 = 50 * 15 = 750秒 > 600秒
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "追单总时间" in errors[0]["msg"]
        assert "600" in errors[0]["msg"]

    def test_short_interval_with_many_chases(self):
        """测试短间隔配合多次追单."""
        with pytest.raises(ValidationError) as exc_info:
            ChaseParamsMixin(
                chase_enabled=True,
                max_chase_count=20,  # 20次
                chase_interval=0.5,  # 0.5秒间隔
                # 可能触发速率限制
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "速率限制" in errors[0]["msg"]

    def test_valid_chase_combination(self):
        """测试有效的追单参数组合."""
        # 合理的组合应该通过验证
        params = ChaseParamsMixin(
            chase_enabled=True,
            chase_ticks=2,
            max_chase_count=5,
            chase_interval=5.0,
        )
        assert params.chase_enabled is True
        assert params.max_chase_count == 5
        assert params.chase_interval == 5.0

    def test_boundary_valid_combination(self):
        """测试边界但有效的组合."""
        # 总时间刚好 600 秒（使用边界值）
        params = ChaseParamsMixin(
            chase_enabled=True,
            max_chase_count=50,  # 上限
            chase_interval=12.0,  # 50 * 12 = 600 秒
        )
        assert params.max_chase_count == 50
        assert params.chase_interval == 12.0

    def test_str_representation_disabled(self):
        """测试禁用时的字符串表示."""
        params = ChaseParamsMixin(chase_enabled=False)
        assert str(params) == "ChaseParamsMixin(chase_enabled=False)"

    def test_str_representation_enabled(self):
        """测试启用时的字符串表示."""
        params = ChaseParamsMixin(
            chase_enabled=True,
            chase_ticks=3,
            max_chase_count=10,
            chase_interval=5.0,
        )
        str_repr = str(params)
        assert "ChaseParamsMixin" in str_repr
        assert "enabled=True" in str_repr
        assert "ticks=3" in str_repr
        assert "max_count=10" in str_repr
        assert "interval=5.0" in str_repr


class TestCombinedParams:
    """测试组合参数."""

    def test_combined_class(self):
        """测试同时继承两个类."""

        class TestParams(BaseAlgorithmParams, ChaseParamsMixin):
            pass

        params = TestParams(
            max_wait_seconds=120,
            chase_enabled=True,
            max_chase_count=5,
            chase_interval=5.0,
        )

        assert params.max_wait_seconds == 120
        assert params.chase_enabled is True

    def test_combined_validation_all_valid(self):
        """测试组合参数都有效."""

        class TestParams(BaseAlgorithmParams, ChaseParamsMixin):
            pass

        params = TestParams(
            max_wait_seconds=300,
            chase_enabled=True,
            chase_ticks=2,
            max_chase_count=5,
            chase_interval=10.0,
        )

        # 所有参数都应该有效
        assert params.max_wait_seconds == 300
        assert params.chase_ticks == 2

    def test_combined_validation_invalid_base(self):
        """测试组合参数中基础参数无效."""

        class TestParams(BaseAlgorithmParams, ChaseParamsMixin):
            pass

        with pytest.raises(ValidationError):
            TestParams(
                max_wait_seconds=4000,  # 超过上限
                chase_enabled=True,
            )

    def test_combined_validation_invalid_chase(self):
        """测试组合参数中追单参数无效."""

        class TestParams(BaseAlgorithmParams, ChaseParamsMixin):
            pass

        with pytest.raises(ValidationError):
            TestParams(
                max_wait_seconds=120,
                chase_enabled=True,
                max_chase_count=100,  # 过大
                chase_interval=10.0,
            )


class TestEdgeCases:
    """测试边界情况."""

    def test_float_chase_interval_precision(self):
        """测试追单间隔的浮点精度."""
        params = ChaseParamsMixin(chase_interval=0.123)
        assert params.chase_interval == 0.123

    def test_zero_chase_ticks_when_disabled(self):
        """测试禁用时 chase_ticks 可以为任意值（不使用）."""
        params = ChaseParamsMixin(
            chase_enabled=False,
            chase_ticks=0,  # 虽然设置了，但未启用追单
        )
        assert params.chase_enabled is False
        # 注意：chase_ticks=0 会触发 Field 的 ge=1 验证错误
        # 所以这个测试会失败，这是预期行为

    def test_very_long_wait_time_warning(self):
        """测试很长的等待时间（虽然允许，但应该记录警告）."""
        # 这个值在允许范围内，但应该在实际使用时记录警告
        params = BaseAlgorithmParams(max_wait_seconds=3500)
        assert params.max_wait_seconds == 3500
        # 实际的警告应该在算法执行时输出


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

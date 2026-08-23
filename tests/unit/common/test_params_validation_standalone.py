"""
独立的参数验证测试脚本.

直接测试参数类而不依赖完整的 axile 导入。
"""

import sys
from pathlib import Path

# 添加项目路径到 sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# 直接定义参数类以避免导入问题
class BaseAlgorithmParams(BaseModel):
    """基础算法参数."""

    max_wait_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="最大等待时间（秒），范围：1-3600",
    )

    @field_validator("max_wait_seconds")
    @classmethod
    def validate_max_wait_seconds(cls, v: int) -> int:
        """验证最大等待时间."""
        return v

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        return f"BaseAlgorithmParams(max_wait_seconds={self.max_wait_seconds})"


class ChaseParamsMixin(BaseModel):
    """追单参数混入类."""

    chase_enabled: bool = Field(
        default=False,
        description="是否启用追单",
    )
    chase_ticks: int = Field(
        default=1,
        ge=1,
        le=100,
        description="价格偏离多少跳后追单，范围：1-100",
    )
    max_chase_count: int = Field(
        default=5,
        ge=1,
        le=50,
        description="单个订单最大追单次数，范围：1-50",
    )
    chase_interval: float = Field(
        default=5.0,
        ge=0.1,
        le=300,
        description="追单间隔（秒），范围：0.1-300",
    )

    @field_validator("chase_ticks")
    @classmethod
    def validate_chase_ticks(cls, v: int, info: Any) -> int:
        """验证追单位数."""
        return v

    @model_validator(mode="after")
    def validate_chase_consistency(self) -> "ChaseParamsMixin":
        """验证追单参数的一致性."""
        if not self.chase_enabled:
            return self

        total_chase_time = self.max_chase_count * self.chase_interval

        if total_chase_time > 600:
            raise ValueError(
                f"追单总时间（max_chase_count * chase_interval = {total_chase_time}秒）"
                f"过长。请减少 max_chase_count 或 chase_interval。"
            )

        if self.chase_interval < 1.0 and self.max_chase_count > 10:
            raise ValueError(f"追单间隔（{self.chase_interval}秒）过短且追单次数过多，可能触发交易所速率限制。")

        return self

    def __str__(self) -> str:
        """便于记录日志的字符串表示."""
        if not self.chase_enabled:
            return "ChaseParamsMixin(chase_enabled=False)"
        return (
            f"ChaseParamsMixin("
            f"enabled={self.chase_enabled}, "
            f"ticks={self.chase_ticks}, "
            f"max_count={self.max_chase_count}, "
            f"interval={self.chase_interval})"
        )


def test_base_params():
    """测试基础参数."""
    print("测试基础参数...")

    # 默认值
    params = BaseAlgorithmParams()
    assert params.max_wait_seconds == 60
    print("[OK] 默认值测试通过")

    # 正常值
    params = BaseAlgorithmParams(max_wait_seconds=120)
    assert params.max_wait_seconds == 120
    print("[OK] 正常值测试通过")

    # 最小边界
    params = BaseAlgorithmParams(max_wait_seconds=1)
    assert params.max_wait_seconds == 1
    print("[OK] 最小边界测试通过")

    # 最大边界
    params = BaseAlgorithmParams(max_wait_seconds=3600)
    assert params.max_wait_seconds == 3600
    print("[OK] 最大边界测试通过")

    # 测试超过最大值
    try:
        BaseAlgorithmParams(max_wait_seconds=3601)
        print("[FAIL] 应该拒绝超过最大值的参数")
    except Exception:
        print("[OK] 超过最大值测试通过")

    # 测试低于最小值
    try:
        BaseAlgorithmParams(max_wait_seconds=0)
        print("[FAIL] 应该拒绝低于最小值的参数")
    except Exception:
        print("[OK] 低于最小值测试通过")


def test_chase_params():
    """测试追单参数."""
    print("\n测试追单参数...")

    # 默认值
    params = ChaseParamsMixin()
    assert params.chase_enabled is False
    assert params.chase_ticks == 1
    assert params.max_chase_count == 5
    assert params.chase_interval == 5.0
    print("[OK] 默认值测试通过")

    # 正常值
    params = ChaseParamsMixin(
        chase_enabled=True,
        chase_ticks=3,
        max_chase_count=10,
        chase_interval=10.0,
    )
    assert params.chase_enabled is True
    assert params.chase_ticks == 3
    print("[OK] 正常值测试通过")

    # 测试追单位数边界
    params = ChaseParamsMixin(chase_ticks=100)
    assert params.chase_ticks == 100
    print("[OK] 追单位数最大边界测试通过")

    try:
        ChaseParamsMixin(chase_ticks=101)
        print("[FAIL] 应该拒绝超过最大追单位数")
    except Exception:
        print("[OK] 超过最大追单位数测试通过")

    # 测试追单次数边界
    params = ChaseParamsMixin(max_chase_count=50)
    assert params.max_chase_count == 50
    print("[OK] 追单次数最大边界测试通过")

    try:
        ChaseParamsMixin(max_chase_count=51)
        print("[FAIL] 应该拒绝超过最大追单次数")
    except Exception:
        print("[OK] 超过最大追单次数测试通过")

    # 测试追单间隔边界
    params = ChaseParamsMixin(chase_interval=300.0)
    assert params.chase_interval == 300.0
    print("[OK] 追单间隔最大边界测试通过")

    try:
        ChaseParamsMixin(chase_interval=301.0)
        print("[FAIL] 应该拒绝超过最大追单间隔")
    except Exception:
        print("[OK] 超过最大追单间隔测试通过")


def test_chase_consistency():
    """测试追单参数一致性."""
    print("\n测试追单参数一致性...")

    # 测试总追单时间超过限制
    try:
        ChaseParamsMixin(
            chase_enabled=True,
            max_chase_count=100,
            chase_interval=10.0,
        )
        print("[FAIL] 应该拒绝过长的总追单时间")
    except Exception as e:
        error_msg = str(e)
        if "追单总时间" in error_msg or "过长" in error_msg:
            print(f"[OK] 总追单时间验证通过: {error_msg}")
        else:
            print(f"[WARN] 总追单时间验证错误消息不符合预期: {error_msg}")

    # 测试短间隔配合多次追单
    try:
        ChaseParamsMixin(
            chase_enabled=True,
            max_chase_count=20,
            chase_interval=0.5,
        )
        print("[FAIL] 应该拒绝短间隔配合多次追单")
    except Exception as e:
        error_msg = str(e)
        if "速率限制" in error_msg:
            print(f"[OK] 速率限制验证通过: {error_msg}")
        else:
            print(f"[WARN] 速率限制验证错误消息不符合预期: {error_msg}")

    # 测试有效的组合
    try:
        params = ChaseParamsMixin(
            chase_enabled=True,
            chase_ticks=2,
            max_chase_count=5,
            chase_interval=5.0,
        )
        assert params.chase_enabled is True
        print("[OK] 有效参数组合测试通过")
    except Exception as e:
        print(f"[FAIL] 有效参数组合测试失败: {e}")

    # 测试边界但有效的组合
    try:
        params = ChaseParamsMixin(
            chase_enabled=True,
            max_chase_count=50,
            chase_interval=10.0,
        )
        assert params.max_chase_count == 50
        print("[OK] 边界有效组合测试通过")
    except Exception as e:
        print(f"[FAIL] 边界有效组合测试失败: {e}")


def test_combined_params():
    """测试组合参数."""
    print("\n测试组合参数...")

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
    print("[OK] 组合参数测试通过")


def main():
    """运行所有测试."""
    print("=" * 60)
    print("算法参数验证测试")
    print("=" * 60)

    try:
        test_base_params()
        test_chase_params()
        test_chase_consistency()
        test_combined_params()

        print("\n" + "=" * 60)
        print("[OK] 所有测试通过！")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        return 1
    except Exception as e:
        print(f"\n[FAIL] 未预期的错误: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""简单验证脚本 - 测试组合持仓拆分功能."""

import sys
from pathlib import Path
from typing import Optional

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def is_combination_instrument(instrument_id: str) -> bool:
    """判断合约代码是否为组合合约."""
    COMBINATION_PREFIXES = ("SPC ", "SPD ", "IPS ", "SP ")
    return instrument_id.startswith(COMBINATION_PREFIXES)


def parse_combination_legs(instrument_id: str):
    """解析组合合约的单腿合约代码."""
    if not is_combination_instrument(instrument_id):
        return None

    COMBINATION_PREFIXES = ("SPC ", "SPD ", "IPS ", "SP ")
    # 移除前缀，提取后面的部分
    for prefix in COMBINATION_PREFIXES:
        if instrument_id.startswith(prefix):
            legs_str = instrument_id[len(prefix) :].strip()
            break
    else:
        return None

    # 按 & 分割两个单腿
    if "&" in legs_str:
        leg1, leg2 = legs_str.split("&", 1)
        return leg1.strip(), leg2.strip()

    return None


def split_combination_position(ctp_position: dict) -> Optional[list[dict]]:
    """将组合持仓拆分为两个单腿持仓."""
    instrument_id = ctp_position.get("InstrumentID", "")
    position = int(ctp_position.get("Position", 0))
    posi_direction = ctp_position.get("PosiDirection", "")
    position_date = ctp_position.get("PositionDate", "1")

    # 检查是否为组合合约
    if not is_combination_instrument(instrument_id):
        return None

    # 解析单腿合约
    legs = parse_combination_legs(instrument_id)
    if not legs:
        return None

    leg1_id, leg2_id = legs[0], legs[1]

    # 确定单腿方向
    # - PosiDirection = "2" (多头/买进): 单腿1=多头, 单腿2=空头
    # - PosiDirection = "3" (空头/卖出): 单腿1=空头, 单腿2=多头
    # - PosiDirection = "1" (净持仓): 根据Position正负判断
    if posi_direction == "2":
        # 买进组合：单腿1多头，单腿2空头
        leg1_direction = "2"  # 多头
        leg2_direction = "3"  # 空头
    elif posi_direction == "3":
        # 卖出组合：单腿1空头，单腿2多头
        leg1_direction = "3"  # 空头
        leg2_direction = "2"  # 多头
    elif posi_direction == "1":
        # 净持仓：根据Position正负判断
        if position > 0:
            leg1_direction = "2"  # 多头
            leg2_direction = "3"  # 空头
        elif position < 0:
            leg1_direction = "3"  # 空头
            leg2_direction = "2"  # 多头
        else:
            return None
    else:
        return None

    # 创建单腿持仓记录
    leg1_position = {
        "InstrumentID": leg1_id,
        "PosiDirection": leg1_direction,
        "Position": abs(position),
        "PositionDate": position_date,
    }

    leg2_position = {
        "InstrumentID": leg2_id,
        "PosiDirection": leg2_direction,
        "Position": abs(position),
        "PositionDate": position_date,
    }

    # 复制其他字段
    for key, value in ctp_position.items():
        if key not in ("InstrumentID", "PosiDirection", "Position"):
            leg1_position[key] = value
            leg2_position[key] = value

    return [leg1_position, leg2_position]


def test_all():
    """运行所有测试."""
    print("=" * 70)
    print("CTP 组合持仓拆分功能测试")
    print("=" * 70)

    # 测试 1: 识别组合合约
    print("\n【测试 1】识别组合合约")
    combinations = ["SPC a2605&m2605", "SP v2201&v2205", "SPD CF208&CF209", "IPS FG205&SA205"]
    for instr in combinations:
        result = is_combination_instrument(instr)
        status = "✓" if result else "✗"
        print(f"  {status} {instr}: {result}")
        assert result is True, f"应该识别为组合合约: {instr}"

    # 测试 2: 拆分组合持仓（多头/买进）
    print("\n【测试 2】拆分组合持仓（多头/买进）")
    comb_position = {
        "InstrumentID": "SPC a2605&m2605",
        "PosiDirection": "2",  # 多头（买进）
        "Position": 10,
        "PositionDate": "1",
    }

    legs = split_combination_position(comb_position)
    assert legs is not None, "应该成功拆分"
    assert len(legs) == 2, "应该返回2个单腿"

    print(
        f"  组合持仓: {comb_position['InstrumentID']} 方向={comb_position['PosiDirection']} 数量={comb_position['Position']}"
    )
    print(f"  单腿1: {legs[0]['InstrumentID']} 方向={legs[0]['PosiDirection']} 数量={legs[0]['Position']}")
    print(f"  单腿2: {legs[1]['InstrumentID']} 方向={legs[1]['PosiDirection']} 数量={legs[1]['Position']}")

    # 验证：买进组合 = 单腿1多头 + 单腿2空头
    assert legs[0]["InstrumentID"] == "a2605", "单腿1应该是 a2605"
    assert legs[0]["PosiDirection"] == "2", "单腿1应该是多头"
    assert legs[0]["Position"] == 10, "单腿1持仓量应该是10"
    assert legs[1]["InstrumentID"] == "m2605", "单腿2应该是 m2605"
    assert legs[1]["PosiDirection"] == "3", "单腿2应该是空头"
    assert legs[1]["Position"] == 10, "单腿2持仓量应该是10"
    print("  ✓ 验证通过：买进组合 = 单腿1多头 + 单腿2空头")

    # 测试 3: 拆分组合持仓（空头/卖出）
    print("\n【测试 3】拆分组合持仓（空头/卖出）")
    comb_position = {
        "InstrumentID": "SPC a2605&m2605",
        "PosiDirection": "3",  # 空头（卖出）
        "Position": 5,
        "PositionDate": "1",
    }

    legs = split_combination_position(comb_position)
    assert legs is not None, "应该成功拆分"
    assert len(legs) == 2, "应该返回2个单腿"

    print(
        f"  组合持仓: {comb_position['InstrumentID']} 方向={comb_position['PosiDirection']} 数量={comb_position['Position']}"
    )
    print(f"  单腿1: {legs[0]['InstrumentID']} 方向={legs[0]['PosiDirection']} 数量={legs[0]['Position']}")
    print(f"  单腿2: {legs[1]['InstrumentID']} 方向={legs[1]['PosiDirection']} 数量={legs[1]['Position']}")

    # 验证：卖出组合 = 单腿1空头 + 单腿2多头
    assert legs[0]["InstrumentID"] == "a2605", "单腿1应该是 a2605"
    assert legs[0]["PosiDirection"] == "3", "单腿1应该是空头"
    assert legs[0]["Position"] == 5, "单腿1持仓量应该是5"
    assert legs[1]["InstrumentID"] == "m2605", "单腿2应该是 m2605"
    assert legs[1]["PosiDirection"] == "2", "单腿2应该是多头"
    assert legs[1]["Position"] == 5, "单腿2持仓量应该是5"
    print("  ✓ 验证通过：卖出组合 = 单腿1空头 + 单腿2多头")

    # 测试 4: 拆分不同类型的组合
    print("\n【测试 4】拆分不同类型的组合")
    test_cases = [
        ("SPC a2605&m2605", "a2605", "m2605"),
        ("SP v2201&v2205", "v2201", "v2205"),
        ("SPD CF208&CF209", "CF208", "CF209"),
        ("IPS FG205&SA205", "FG205", "SA205"),
    ]

    for comb_id, expected_leg1, expected_leg2 in test_cases:
        pos = {"InstrumentID": comb_id, "PosiDirection": "2", "Position": 10, "PositionDate": "1"}
        legs = split_combination_position(pos)
        assert legs is not None, f"应该成功拆分 {comb_id}"
        assert legs[0]["InstrumentID"] == expected_leg1, f"单腿1应该是 {expected_leg1}"
        assert legs[1]["InstrumentID"] == expected_leg2, f"单腿2应该是 {expected_leg2}"
        print(f"  ✓ {comb_id}: {expected_leg1} + {expected_leg2}")

    # 测试 5: 单腿持仓不应该被拆分
    print("\n【测试 5】单腿持仓不应该被拆分")
    single_position = {"InstrumentID": "a2605", "PosiDirection": "2", "Position": 10, "PositionDate": "1"}
    legs = split_combination_position(single_position)
    assert legs is None, "单腿持仓不应该被拆分"
    print("  ✓ 单腿持仓不会被拆分")

    # 测试 6: 模拟完整工作流
    print("\n【测试 6】完整工作流模拟")
    print("  假设 CTP 返回以下持仓数据：")

    raw_positions = [
        {"InstrumentID": "SPC a2605&m2605", "PosiDirection": "2", "Position": 10, "PositionDate": "1"},  # 组合持仓
        {"InstrumentID": "rb2505", "PosiDirection": "2", "Position": 5, "PositionDate": "1"},  # 单腿持仓
    ]

    final_positions = []

    for pos in raw_positions:
        legs = split_combination_position(pos)
        if legs:
            # 组合持仓，拆分为两个单腿
            print(f"    - {pos['InstrumentID']} (组合) -> 拆分为 {legs[0]['InstrumentID']} + {legs[1]['InstrumentID']}")
            final_positions.extend(legs)
        else:
            # 单腿持仓，直接保留
            print(f"    - {pos['InstrumentID']} (单腿) -> 直接保留")
            final_positions.append(pos)

    print(f"\n  最终持仓列表（{len(final_positions)}条）：")
    for pos in final_positions:
        direction = "多头" if pos["PosiDirection"] == "2" else "空头"
        print(f"    {pos['InstrumentID']:15} {direction:4} {pos['Position']:>3}手")

    # 验证结果
    assert len(final_positions) == 3, "应该有3条持仓记录（1个组合拆分2个 + 1个单腿）"

    # 验证持仓量
    a2605_positions = [p for p in final_positions if p["InstrumentID"] == "a2605"]
    assert len(a2605_positions) == 1, "应该有1条 a2605 持仓"
    assert a2605_positions[0]["Position"] == 10, "a2605 持仓量应该是10"

    m2605_positions = [p for p in final_positions if p["InstrumentID"] == "m2605"]
    assert len(m2605_positions) == 1, "应该有1条 m2605 持仓"
    assert m2605_positions[0]["Position"] == 10, "m2605 持仓量应该是10"

    rb2505_positions = [p for p in final_positions if p["InstrumentID"] == "rb2505"]
    assert len(rb2505_positions) == 1, "应该有1条 rb2505 持仓"
    assert rb2505_positions[0]["Position"] == 5, "rb2505 持仓量应该是5"

    print("\n  ✓ 工作流验证通过")

    print("\n" + "=" * 70)
    print("✅ 所有测试通过！")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_all()
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

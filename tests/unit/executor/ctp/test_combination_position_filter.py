"""CTP 组合持仓过滤器单元测试."""

from axile.executor.ctp.core.combination_position_filter import (
    get_combination_info,
    is_combination_instrument,
    parse_combination_legs,
    should_filter_position,
    split_combination_position,
)


class TestCombinationInstrument:
    """测试组合合约识别功能."""

    def test_spc_combination(self):
        """测试大商所跨品种套利合约识别."""
        assert is_combination_instrument("SPC a2605&m2605") is True
        assert is_combination_instrument("SPC y1909&p1909") is True
        assert is_combination_instrument("SPC c2301&cs2301") is True

    def test_sp_combination(self):
        """测试大商所跨期套利合约识别."""
        assert is_combination_instrument("SP v2201&v2205") is True
        assert is_combination_instrument("SP m1809&m1901") is True

    def test_spd_combination(self):
        """测试郑商所跨期套利合约识别."""
        assert is_combination_instrument("SPD CF208&CF209") is True
        assert is_combination_instrument("SPD MA305&MA309") is True

    def test_ips_combination(self):
        """测试郑商所跨品种套利合约识别."""
        assert is_combination_instrument("IPS FG205&SA205") is True
        assert is_combination_instrument("IPS SR305&SM305") is True

    def test_single_leg_instruments(self):
        """测试单腿合约识别（非组合合约）."""
        assert is_combination_instrument("a2605") is False
        assert is_combination_instrument("m2605") is False
        assert is_combination_instrument("rb2505") is False
        assert is_combination_instrument("CF208") is False
        assert is_combination_instrument("v2201") is False

    def test_edge_cases(self):
        """测试边界情况."""
        # 空字符串
        assert is_combination_instrument("") is False

        # 只包含前缀但没有合约代码
        assert is_combination_instrument("SPC ") is True
        assert is_combination_instrument("SP ") is True

        # 前缀大小写敏感（应该只匹配大写）
        assert is_combination_instrument("sp a2605&m2605") is False
        assert is_combination_instrument("Sp a2605&m2605") is False


class TestParseCombinationLegs:
    """测试组合合约单腿解析功能."""

    def test_parse_spc_legs(self):
        """测试解析 SPC 组合的单腿."""
        result = parse_combination_legs("SPC a2605&m2605")
        assert result == ("a2605", "m2605")

        result = parse_combination_legs("SPC y1909&p1909")
        assert result == ("y1909", "p1909")

    def test_parse_sp_legs(self):
        """测试解析 SP 组合的单腿."""
        result = parse_combination_legs("SP v2201&v2205")
        assert result == ("v2201", "v2205")

        result = parse_combination_legs("SP m1809&m1901")
        assert result == ("m1809", "m1901")

    def test_parse_spd_legs(self):
        """测试解析 SPD 组合的单腿."""
        result = parse_combination_legs("SPD CF208&CF209")
        assert result == ("CF208", "CF209")

    def test_parse_ips_legs(self):
        """测试解析 IPS 组合的单腿."""
        result = parse_combination_legs("IPS FG205&SA205")
        assert result == ("FG205", "SA205")

    def test_parse_single_leg_returns_none(self):
        """测试解析单腿合约返回 None."""
        assert parse_combination_legs("a2605") is None
        assert parse_combination_legs("rb2505") is None
        assert parse_combination_legs("") is None

    def test_parse_malformed_combination(self):
        """测试格式错误的组合合约."""
        # 缺少 & 分隔符
        assert parse_combination_legs("SPC a2605 m2605") is None

        # 只有单腿
        assert parse_combination_legs("SPC a2605") is None


class TestGetCombinationInfo:
    """测试获取组合合约详细信息."""

    def test_spc_info(self):
        """测试获取 SPC 组合信息."""
        info = get_combination_info("SPC a2605&m2605")
        assert info is not None
        assert info["type"] == "SPC"
        assert info["leg1"] == "a2605"
        assert info["leg2"] == "m2605"
        assert info["description"] == "大商所跨品种套利"

    def test_sp_info(self):
        """测试获取 SP 组合信息."""
        info = get_combination_info("SP v2201&v2205")
        assert info is not None
        assert info["type"] == "SP"
        assert info["leg1"] == "v2201"
        assert info["leg2"] == "v2205"
        assert info["description"] == "大商所跨期套利"

    def test_spd_info(self):
        """测试获取 SPD 组合信息."""
        info = get_combination_info("SPD CF208&CF209")
        assert info is not None
        assert info["type"] == "SPD"
        assert info["leg1"] == "CF208"
        assert info["leg2"] == "CF209"
        assert info["description"] == "郑商所跨期套利"

    def test_ips_info(self):
        """测试获取 IPS 组合信息."""
        info = get_combination_info("IPS FG205&SA205")
        assert info is not None
        assert info["type"] == "IPS"
        assert info["leg1"] == "FG205"
        assert info["leg2"] == "SA205"
        assert info["description"] == "郑商所跨品种套利"

    def test_single_leg_returns_none(self):
        """测试单腿合约返回 None."""
        assert get_combination_info("a2605") is None
        assert get_combination_info("rb2505") is None


class TestShouldFilterPosition:
    """测试持仓过滤判断功能."""

    def test_filter_dict_with_combination(self):
        """测试过滤组合持仓（字典格式）."""
        # 组合持仓字典
        comb_position = {
            "InstrumentID": "SPC a2605&m2605",
            "Position": 10,
            "PosiDirection": "2",
        }
        assert should_filter_position(comb_position) is True

    def test_not_filter_dict_with_single_leg(self):
        """测试不过滤单腿持仓（字典格式）."""
        # 单腿持仓字典
        single_position = {
            "InstrumentID": "a2605",
            "Position": 10,
            "PosiDirection": "2",
        }
        assert should_filter_position(single_position) is False

    def test_filter_position_with_object(self):
        """测试过滤组合持仓（对象格式）."""

        # 创建模拟对象
        class MockPosition:
            def __init__(self, instrument_id: str):
                self.InstrumentID = instrument_id

        comb_position = MockPosition("SPC a2605&m2605")
        assert should_filter_position(comb_position) is True

        single_position = MockPosition("a2605")
        assert should_filter_position(single_position) is False

    def test_filter_empty_dict(self):
        """测试空字典不过滤."""
        empty_position = {}
        assert should_filter_position(empty_position) is False

    def test_filter_dict_without_instrument_id(self):
        """测试没有 InstrumentID 键的字典不过滤."""
        position = {"Position": 10, "PosiDirection": "2"}
        assert should_filter_position(position) is False

    def test_all_combination_types(self):
        """测试所有类型的组合合约都会被过滤."""
        combinations = [
            {"InstrumentID": "SPC a2605&m2605", "Position": 10},
            {"InstrumentID": "SP v2201&v2205", "Position": 10},
            {"InstrumentID": "SPD CF208&CF209", "Position": 10},
            {"InstrumentID": "IPS FG205&SA205", "Position": 10},
        ]

        for pos in combinations:
            assert should_filter_position(pos) is True, f"Failed for {pos['InstrumentID']}"

    def test_all_single_leg_types(self):
        """测试各种单腿合约都不会被过滤."""
        singles = [
            {"InstrumentID": "a2605", "Position": 10},
            {"InstrumentID": "m2605", "Position": 10},
            {"InstrumentID": "rb2505", "Position": 10},
            {"InstrumentID": "CF208", "Position": 10},
            {"InstrumentID": "v2201", "Position": 10},
        ]

        for pos in singles:
            assert should_filter_position(pos) is False, f"Failed for {pos['InstrumentID']}"


class TestSplitCombinationPosition:
    """测试组合持仓拆分功能."""

    def test_split_buy_combination_dict(self):
        """买进组合应拆成单腿1多头、单腿2空头。"""
        position = {
            "InstrumentID": "SPC a2605&m2605",
            "PosiDirection": "2",
            "Position": 10,
            "PositionDate": "1",
            "ExchangeID": "DCE",
        }

        result = split_combination_position(position)

        assert result == [
            {
                "InstrumentID": "a2605",
                "PosiDirection": "2",
                "Position": 10,
                "PositionDate": "1",
                "ExchangeID": "DCE",
                "combination_origin": "SPC a2605&m2605",
            },
            {
                "InstrumentID": "m2605",
                "PosiDirection": "3",
                "Position": 10,
                "PositionDate": "1",
                "ExchangeID": "DCE",
                "combination_origin": "SPC a2605&m2605",
            },
        ]

    def test_split_net_short_combination_uses_position_sign(self):
        """净持仓为负时，应拆成单腿1空头、单腿2多头。"""
        position = {
            "InstrumentID": "SPC a2605&m2605",
            "PosiDirection": "1",
            "Position": -6,
            "PositionDate": "2",
        }

        result = split_combination_position(position)

        assert result == [
            {
                "InstrumentID": "a2605",
                "PosiDirection": "3",
                "Position": 6,
                "PositionDate": "2",
                "combination_origin": "SPC a2605&m2605",
            },
            {
                "InstrumentID": "m2605",
                "PosiDirection": "2",
                "Position": 6,
                "PositionDate": "2",
                "combination_origin": "SPC a2605&m2605",
            },
        ]

    def test_split_combination_copies_object_metadata(self):
        """对象输入也应复制公共元数据到两个单腿。"""

        class MockPosition:
            def __init__(self) -> None:
                self.InstrumentID = "SP v2201&v2205"
                self.PosiDirection = "3"
                self.Position = 4
                self.PositionDate = "1"
                self.ExchangeID = "DCE"

        result = split_combination_position(MockPosition())

        assert result is not None
        assert result[0]["InstrumentID"] == "v2201"
        assert result[0]["PosiDirection"] == "3"
        assert result[0]["ExchangeID"] == "DCE"
        assert result[0]["combination_origin"] == "SP v2201&v2205"
        assert result[1]["InstrumentID"] == "v2205"
        assert result[1]["PosiDirection"] == "2"
        assert result[1]["ExchangeID"] == "DCE"
        assert result[1]["combination_origin"] == "SP v2201&v2205"

    def test_split_total_volume_equals_combination_volume(self):
        """拆腿后总持仓量应等于组合持仓量乘以 2（每腿继承原持仓量）。

        这对应设计文档 §4 Sprint 4 中"拆腿后总量 = 非组合 + 拆腿和"的契约：
        组合持仓拆成两条单腿，每条腿的 Position 都等于原组合 Position。
        """
        position = {
            "InstrumentID": "SPC a2605&m2605",
            "PosiDirection": "2",
            "Position": 7,
            "PositionDate": "1",
        }

        result = split_combination_position(position)

        assert result is not None
        assert len(result) == 2
        assert result[0]["Position"] == 7
        assert result[1]["Position"] == 7
        # 两条腿都应携带原始组合代码，便于审计追溯。
        assert result[0]["combination_origin"] == "SPC a2605&m2605"
        assert result[1]["combination_origin"] == "SPC a2605&m2605"

"""CTP 合约种类识别工具的单元测试.

覆盖 ``classify`` 对 ``ProductClass`` 全分支取值的归类、``is_option*`` 系列
辅助函数，以及 ``option_metadata`` 仅在期权合约上返回完整元数据。
"""

from __future__ import annotations

import pytest

from axile.executor.ctp.core.objects import InstrumentField
from axile.executor.ctp.utils.instrument_kind import (
    CtpInstrumentKind,
    classify,
    is_future,
    is_option,
    is_option_call,
    is_option_put,
    option_metadata,
)


def _instrument(**overrides: object) -> InstrumentField:
    """构造测试用的 InstrumentField，默认填充期权字段。"""
    payload: dict[str, object] = {
        "InstrumentID": "m2510-C-3100",
        "ProductID": "m",
        "ProductClass": "2",
        "VolumeMultiple": 10,
        "OptionsType": "1",
        "StrikePrice": 3100.0,
        "UnderlyingInstrID": "m2510",
        "UnderlyingMultiple": 1.0,
        "ExpireDate": "20251015",
    }
    payload.update(overrides)
    return InstrumentField(**payload)  # type: ignore[arg-type]


class TestClassify:
    """覆盖 ``classify`` 对 ProductClass 的全分支归类。"""

    def test_future_product_class_one(self) -> None:
        instrument = _instrument(ProductClass="1", InstrumentID="rb2510", OptionsType="")
        assert classify(instrument) is CtpInstrumentKind.FUTURE

    def test_option_product_class_two(self) -> None:
        instrument = _instrument(ProductClass="2")
        assert classify(instrument) is CtpInstrumentKind.OPTION

    def test_combination_product_class_three(self) -> None:
        instrument = _instrument(ProductClass="3", InstrumentID="SPC a2605&m2605", OptionsType="")
        assert classify(instrument) is CtpInstrumentKind.COMBINATION

    @pytest.mark.parametrize("product_class", ["", "0", "4", "9", "X"])
    def test_unknown_product_class(self, product_class: str) -> None:
        instrument = _instrument(ProductClass=product_class, OptionsType="")
        assert classify(instrument) is CtpInstrumentKind.UNKNOWN

    def test_none_returns_unknown(self) -> None:
        assert classify(None) is CtpInstrumentKind.UNKNOWN


class TestOptionFlags:
    """覆盖 ``is_option`` / ``is_option_call`` / ``is_option_put``。"""

    def test_is_option_true_for_call_option(self) -> None:
        assert is_option(_instrument(OptionsType="1")) is True

    def test_is_option_true_for_put_option(self) -> None:
        assert is_option(_instrument(OptionsType="2")) is True

    def test_is_option_false_for_future(self) -> None:
        assert is_option(_instrument(ProductClass="1", OptionsType="")) is False

    def test_is_future_true_for_future(self) -> None:
        assert is_future(_instrument(ProductClass="1", OptionsType="")) is True

    def test_is_future_false_for_option(self) -> None:
        assert is_future(_instrument(ProductClass="2")) is False

    def test_is_option_call_only_for_call(self) -> None:
        assert is_option_call(_instrument(OptionsType="1")) is True
        assert is_option_call(_instrument(OptionsType="2")) is False

    def test_is_option_put_only_for_put(self) -> None:
        assert is_option_put(_instrument(OptionsType="2")) is True
        assert is_option_put(_instrument(OptionsType="1")) is False

    def test_option_call_false_for_future(self) -> None:
        assert is_option_call(_instrument(ProductClass="1", OptionsType="")) is False

    def test_option_put_false_for_none(self) -> None:
        assert is_option_put(None) is False


class TestOptionMetadata:
    """覆盖 ``option_metadata`` 在期权与非期权上的输出差异。"""

    def test_returns_full_metadata_for_call(self) -> None:
        instrument = _instrument(
            OptionsType="1",
            StrikePrice=3100.5,
            UnderlyingInstrID="m2510",
            UnderlyingMultiple=10.0,
            ExpireDate="20251015",
        )
        assert option_metadata(instrument) == {
            "option_type": "call",
            "strike_price": 3100.5,
            "underlying": "m2510",
            "underlying_multiple": 10.0,
            "expire_date": "20251015",
        }

    def test_returns_full_metadata_for_put(self) -> None:
        instrument = _instrument(OptionsType="2")
        metadata = option_metadata(instrument)
        assert metadata["option_type"] == "put"

    def test_returns_empty_for_future(self) -> None:
        assert option_metadata(_instrument(ProductClass="1", OptionsType="")) == {}

    def test_returns_empty_for_none(self) -> None:
        assert option_metadata(None) == {}

    def test_unknown_option_type_normalised(self) -> None:
        instrument = _instrument(OptionsType="X")
        metadata = option_metadata(instrument)
        # OptionsType="X" 会被 ``classify`` 标为 OPTION（因为 ProductClass=="2"），
        # 但具体看涨/看跌字段无效，应输出 ``unknown``。
        assert metadata["option_type"] == "unknown"

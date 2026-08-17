"""CTP 合约种类识别工具.

提供 ``CtpInstrumentKind`` 枚举与配套判断函数，把"期货 / 期权 / 组合"
三类合约的识别集中到一处，避免在 ``trader.py`` / ``data_converter.py``
等模块中以 ``ProductClass == "2"`` 的散点方式判断。

Notes
-----
``InstrumentField.ProductClass`` 的取值由 CTP 协议定义：

- ``"1"`` 期货
- ``"2"`` 期权
- ``"3"`` 组合（套利合约，对应单腿持仓由 ``combination_position_filter`` 拆分）

``OptionsType`` 取值：

- ``"1"`` 看涨（call）
- ``"2"`` 看跌（put）
"""

from __future__ import annotations

from enum import Enum

from axile.executor.ctp.core.objects import InstrumentField


class CtpInstrumentKind(str, Enum):
    """CTP 合约种类枚举."""

    FUTURE = "future"
    OPTION = "option"
    COMBINATION = "combination"
    UNKNOWN = "unknown"


_PRODUCT_CLASS_MAP: dict[str, CtpInstrumentKind] = {
    "1": CtpInstrumentKind.FUTURE,
    "2": CtpInstrumentKind.OPTION,
    "3": CtpInstrumentKind.COMBINATION,
}


def classify(instrument: InstrumentField | None) -> CtpInstrumentKind:
    """
    将合约对象归类为期货 / 期权 / 组合 / 未知.

    Parameters
    ----------
    instrument : InstrumentField | None
        CTP 合约对象；为 ``None`` 时返回 ``UNKNOWN``。

    Returns
    -------
    CtpInstrumentKind
        归类结果。

    Examples
    --------
    >>> from axile.executor.ctp.core.objects import InstrumentField
    >>> classify(InstrumentField(InstrumentID="rb2510", ProductClass="1"))
    <CtpInstrumentKind.FUTURE: 'future'>
    >>> classify(InstrumentField(InstrumentID="m2510-C-3100", ProductClass="2"))
    <CtpInstrumentKind.OPTION: 'option'>
    """
    if instrument is None:
        return CtpInstrumentKind.UNKNOWN
    return _PRODUCT_CLASS_MAP.get(instrument.ProductClass, CtpInstrumentKind.UNKNOWN)


def is_option(instrument: InstrumentField | None) -> bool:
    """
    判断给定合约是否为期权.

    Parameters
    ----------
    instrument : InstrumentField | None
        合约对象。

    Returns
    -------
    bool
        是期权时返回 ``True``，其它情况（期货 / 组合 / 未知）返回 ``False``。
    """
    return classify(instrument) is CtpInstrumentKind.OPTION


def is_future(instrument: InstrumentField | None) -> bool:
    """
    判断给定合约是否为期货.

    Parameters
    ----------
    instrument : InstrumentField | None
        合约对象。

    Returns
    -------
    bool
        是期货时返回 ``True``。
    """
    return classify(instrument) is CtpInstrumentKind.FUTURE


def is_option_call(instrument: InstrumentField | None) -> bool:
    """
    判断期权合约是否为看涨期权.

    Parameters
    ----------
    instrument : InstrumentField | None
        合约对象。

    Returns
    -------
    bool
        非期权或非看涨时返回 ``False``。
    """
    return is_option(instrument) and instrument is not None and instrument.OptionsType == "1"


def is_option_put(instrument: InstrumentField | None) -> bool:
    """
    判断期权合约是否为看跌期权.

    Parameters
    ----------
    instrument : InstrumentField | None
        合约对象。

    Returns
    -------
    bool
        非期权或非看跌时返回 ``False``。
    """
    return is_option(instrument) and instrument is not None and instrument.OptionsType == "2"


def option_metadata(instrument: InstrumentField | None) -> dict[str, object]:
    """
    提取期权合约的关键元数据字段.

    Parameters
    ----------
    instrument : InstrumentField | None
        合约对象；为 ``None`` 或非期权时返回空字典。

    Returns
    -------
    dict[str, object]
        包含 ``option_type`` / ``strike_price`` / ``underlying`` /
        ``underlying_multiple`` / ``expire_date`` 字段的字典。``option_type``
        会被规范化为 ``"call"`` / ``"put"`` / ``"unknown"``。

    Notes
    -----
    本函数面向 ``UnifiedPosition.extra`` 场景，仅返回 JSON 可序列化的标量
    （字符串 / 数字），便于审计与 UI 展示。
    """
    if not is_option(instrument) or instrument is None:
        return {}

    options_type = {"1": "call", "2": "put"}.get(instrument.OptionsType, "unknown")
    return {
        "option_type": options_type,
        "strike_price": float(instrument.StrikePrice),
        "underlying": instrument.UnderlyingInstrID,
        "underlying_multiple": float(instrument.UnderlyingMultiple),
        "expire_date": instrument.ExpireDate,
    }

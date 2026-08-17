"""CTP 组合持仓过滤器模块.

用于识别和过滤 CTP 系统返回的组合持仓记录（套利持仓）。

CTP 系统在处理套利交易时，会将同一品种不同合约的多空持仓自动合并为组合持仓返回。
例如：
- 持有 a2605（豆粕2505）的多头
- 持有 m2605（豆油2505）的空头
- CTP 会将其合并为 SPC a2605&m2605 的组合持仓返回

本模块提供了识别和过滤组合持仓的工具函数，帮助交易系统只保留单腿合约的持仓数据。

参考资料：
- CTP组合合约浅析: https://www.bilibili.com/read/cv23638244
- 期货CTP接口组合合约持仓计算规则: https://zhuanlan.zhihu.com/p/150725102
"""

from __future__ import annotations

from typing import Any

import loguru

from axile.executor.ctp.core.objects import PositionField
from axile.executor.ctp.core.openctp_compat import CThostFtdcInvestorPositionField

# 前缀按更具体的类型优先，避免 ``SP `` 抢先匹配 ``SPC `` 与 ``SPD ``。
COMBINATION_PREFIXES = ("SPC ", "SPD ", "IPS ", "SP ")
COMBINATION_TYPE_DESCRIPTIONS = {
    "SPC": "大商所跨品种套利",
    "SPD": "郑商所跨期套利",
    "IPS": "郑商所跨品种套利",
    "SP": "大商所跨期套利",
}

logger = loguru.logger


def is_combination_instrument(instrument_id: str) -> bool:
    """
    判断合约代码是否为组合合约.

    通过检查合约代码的前缀来识别组合合约：
    - "SPC " - 大商所跨品种套利（如 SPC a2605&m2605）
    - "SPD " - 郑商所跨期套利（如 SPD CF208&CF209）
    - "IPS " - 郑商所跨品种套利（如 IPS FG205&SA205）
    - "SP " - 大商所跨期套利（如 SP v2201&v2205）

    Parameters
    ----------
    instrument_id : str
        合约代码。

    Returns
    -------
    bool
        是组合合约时返回 ``True``，否则返回 ``False``。

    Examples
    --------
        >>> is_combination_instrument("SPC a2605&m2605")
        True
        >>> is_combination_instrument("SP v2201&v2205")
        True
        >>> is_combination_instrument("a2605")
        False
        >>> is_combination_instrument("rb2505")
        False
    """
    return instrument_id.startswith(COMBINATION_PREFIXES)


def should_filter_position(
    ctp_position: CThostFtdcInvestorPositionField | PositionField | dict,
) -> bool:
    """
    判断持仓记录是否应该被过滤.

    如果是组合持仓记录，则应该被过滤（返回 True）。
    如果是单腿持仓记录，则不应该被过滤（返回 False）。

    Parameters
    ----------
    ctp_position : CThostFtdcInvestorPositionField | PositionField | dict
        CTP 持仓数据，可以是原始结构体、Pydantic 模型或包含 ``InstrumentID`` 的字典。

    Returns
    -------
    bool
        需要过滤时返回 ``True``，否则返回 ``False``。

    Examples
    --------
        >>> # 模拟组合持仓
        >>> pos_dict = {"InstrumentID": "SPC a2605&m2605", "Position": 10}
        >>> should_filter_position(pos_dict)
        True

        >>> # 模拟单腿持仓
        >>> pos_dict = {"InstrumentID": "a2605", "Position": 10}
        >>> should_filter_position(pos_dict)
        False
    """
    # 过滤逻辑发生在统一模型转换之前，因此要同时接受字典、Pydantic 模型和原生 CTP 结构体。
    if isinstance(ctp_position, dict):
        instrument_id = ctp_position.get("InstrumentID", "")
    elif hasattr(ctp_position, "InstrumentID"):
        instrument_id = str(ctp_position.InstrumentID)
    else:
        logger.warning(f"无法识别的持仓类型: {type(ctp_position)}")
        return False

    return is_combination_instrument(instrument_id)


def log_filtered_position(
    ctp_position: CThostFtdcInvestorPositionField | PositionField | dict,
    reason: str = "组合持仓",
) -> None:
    """
    记录被过滤的持仓信息.

    Parameters
    ----------
    ctp_position : CThostFtdcInvestorPositionField | PositionField | dict
        被过滤的持仓数据。
    reason : str, default="组合持仓"
        过滤原因。
    """
    if isinstance(ctp_position, dict):
        instrument_id = ctp_position.get("InstrumentID", "")
        position = ctp_position.get("Position", 0)
    elif hasattr(ctp_position, "InstrumentID"):
        instrument_id = str(ctp_position.InstrumentID)
        position = int(getattr(ctp_position, "Position", 0))
    else:
        logger.warning(f"无法记录过滤信息: 不支持的类型 {type(ctp_position)}")
        return

    logger.debug(f"🚫 过滤持仓: {instrument_id} ({reason}), 持仓量={position}")


def parse_combination_legs(instrument_id: str) -> tuple[str, str] | None:
    """
    解析组合合约的单腿合约代码.

    从组合合约代码中提取两个单腿合约的代码。
    例如：
    - "SPC a2605&m2605" -> ("a2605", "m2605")
    - "SP v2201&v2205" -> ("v2201", "v2205")

    Parameters
    ----------
    instrument_id : str
        组合合约代码。

    Returns
    -------
    tuple[str, str] | None
        解析成功时返回两个单腿合约代码；若不是组合合约或解析失败则返回 ``None``。

    Examples
    --------
        >>> parse_combination_legs("SPC a2605&m2605")
        ('a2605', 'm2605')
        >>> parse_combination_legs("SP v2201&v2205")
        ('v2201', 'v2205')
        >>> parse_combination_legs("a2605") is None
        True
    """
    if not is_combination_instrument(instrument_id):
        return None

    # 这里沿用前缀表的顺序匹配，确保更窄的组合类型不会被 ``SP `` 这类宽匹配吞掉。
    for prefix in COMBINATION_PREFIXES:
        if instrument_id.startswith(prefix):
            legs_str = instrument_id[len(prefix) :].strip()
            break
    else:
        return None

    if "&" in legs_str:
        leg1, leg2 = legs_str.split("&", 1)
        return leg1.strip(), leg2.strip()

    return None


def get_combination_info(instrument_id: str) -> dict[str, str] | None:
    """
    获取组合合约的详细信息.

    Parameters
    ----------
    instrument_id : str
        合约代码。

    Returns
    -------
    dict[str, str] | None
        组合合约信息字典；若不是组合合约则返回 ``None``。

    Examples
    --------
        >>> get_combination_info("SPC a2605&m2605")
        {'type': 'SPC', 'leg1': 'a2605', 'leg2': 'm2605', 'description': '大商所跨品种套利'}
    """
    if not is_combination_instrument(instrument_id):
        return None

    comb_type: str = ""
    for prefix in COMBINATION_PREFIXES:
        if instrument_id.startswith(prefix):
            comb_type = prefix.strip()
            break

    # 详情展示复用和过滤完全相同的拆腿口径，避免 UI/日志和撮合侧看到不同的单腿结果。
    legs = parse_combination_legs(instrument_id)
    if not legs:
        return None

    return {
        "type": comb_type,
        "leg1": legs[0],
        "leg2": legs[1],
        "description": COMBINATION_TYPE_DESCRIPTIONS.get(comb_type, "未知组合类型"),
    }


def split_combination_position(
    ctp_position: CThostFtdcInvestorPositionField | PositionField | dict,
) -> list[dict[str, Any]] | None:
    """
    将组合持仓拆分为两个单腿持仓.

    CTP 组合持仓的规则：
    - 买进组合 = 买进单腿1 + 卖出单腿2
    - 卖出组合 = 卖出单腿1 + 买进单腿2

    例如：
    - 买进 "SPC a2605&m2605" = 买进 a2605（多头）+ 卖出 m2605（空头）
    - 卖出 "SPC a2605&m2605" = 卖出 a2605（空头）+ 买进 m2605（多头）

    Parameters
    ----------
    ctp_position : CThostFtdcInvestorPositionField | PositionField | dict
        CTP 组合持仓数据。

    Returns
    -------
    list[dict[str, Any]] | None
        拆分后的两个单腿持仓记录；若拆分失败则返回 ``None``。

    Examples
    --------
        >>> # 模拟组合持仓
        >>> pos = {
        ...     "InstrumentID": "SPC a2605&m2605",
        ...     "PosiDirection": "2",  # 买进（多头）
        ...     "Position": 10,
        ...     "PositionDate": "1",
        ... }
        >>> legs = split_combination_position(pos)
        >>> legs[0]["InstrumentID"], legs[0]["PosiDirection"]
        ('a2605', '2')  # 单腿1：多头
        >>> legs[1]["InstrumentID"], legs[1]["PosiDirection"]
        ('m2605', '3')  # 单腿2：空头
    """
    position_info = _extract_combination_position_fields(ctp_position)
    if position_info is None:
        return None

    instrument_id, position, posi_direction, position_date = position_info

    if not is_combination_instrument(instrument_id):
        return None

    legs = parse_combination_legs(instrument_id)
    if not legs:
        logger.warning(f"无法解析组合合约的单腿: {instrument_id}")
        return None

    leg_directions = _resolve_combination_leg_directions(
        instrument_id=instrument_id,
        position=position,
        posi_direction=posi_direction,
    )
    if leg_directions is None:
        return None

    leg1_position = _build_split_leg_position(
        instrument_id=legs[0],
        posi_direction=leg_directions[0],
        position=position,
        position_date=position_date,
        combination_origin=instrument_id,
    )
    leg2_position = _build_split_leg_position(
        instrument_id=legs[1],
        posi_direction=leg_directions[1],
        position=position,
        position_date=position_date,
        combination_origin=instrument_id,
    )

    # 拆分后的两条腿要尽量继承原始持仓元数据，这样平今/平昨和审计链路仍能按单腿继续工作。
    _copy_position_metadata(ctp_position, leg1_position, leg2_position)
    return [leg1_position, leg2_position]


def _extract_combination_position_fields(
    ctp_position: CThostFtdcInvestorPositionField | PositionField | dict,
) -> tuple[str, int, str, str] | None:
    """提取组合持仓拆分所需的公共字段。"""
    if isinstance(ctp_position, dict):
        return (
            str(ctp_position.get("InstrumentID", "")),
            int(ctp_position.get("Position", 0)),
            str(ctp_position.get("PosiDirection", "")),
            str(ctp_position.get("PositionDate", "1")),
        )

    if hasattr(ctp_position, "InstrumentID"):
        return (
            str(ctp_position.InstrumentID),
            int(getattr(ctp_position, "Position", 0)),
            str(getattr(ctp_position, "PosiDirection", "")),
            str(getattr(ctp_position, "PositionDate", "1")),
        )

    logger.warning(f"无法识别的持仓类型: {type(ctp_position)}")
    return None


def _resolve_combination_leg_directions(
    *,
    instrument_id: str,
    position: int,
    posi_direction: str,
) -> tuple[str, str] | None:
    """根据组合持仓方向解析两个单腿的多空方向。"""
    if posi_direction == "2":
        return "2", "3"
    if posi_direction == "3":
        return "3", "2"
    if posi_direction != "1":
        logger.warning(f"未知的持仓方向: {posi_direction}")
        return None

    if position > 0:
        return "2", "3"
    if position < 0:
        return "3", "2"

    logger.warning(f"组合持仓量为0: {instrument_id}")
    return None


def _build_split_leg_position(
    *,
    instrument_id: str,
    posi_direction: str,
    position: int,
    position_date: str,
    combination_origin: str | None = None,
) -> dict[str, Any]:
    """
    构造拆分后的单腿持仓字典.

    Parameters
    ----------
    instrument_id : str
        拆分后的单腿合约代码。
    posi_direction : str
        多空方向（CTP 协议字符串）。
    position : int
        原组合持仓量；拆腿后的两条腿都使用同一个绝对值。
    position_date : str
        持仓日期类型（今仓 / 昨仓）。
    combination_origin : str | None, optional
        原始组合合约代码（如 ``"SPC a2605&m2605"``），写入字典中
        作为 ``combination_origin`` 字段，供 ``data_converter`` 透传到
        ``UnifiedPosition.extra``，用于审计追溯。

    Returns
    -------
    dict[str, Any]
        构造后的单腿持仓字典。
    """
    payload: dict[str, Any] = {
        "InstrumentID": instrument_id,
        "PosiDirection": posi_direction,
        "Position": abs(position),
        "PositionDate": position_date,
    }
    if combination_origin:
        payload["combination_origin"] = combination_origin
    return payload


def _copy_position_metadata(
    ctp_position: CThostFtdcInvestorPositionField | PositionField | dict,
    *leg_positions: dict[str, Any],
) -> None:
    """将原始持仓中的公共字段复制到拆分后的单腿持仓。"""
    excluded_keys = {"InstrumentID", "PosiDirection", "Position"}
    if isinstance(ctp_position, dict):
        for key, value in ctp_position.items():
            if key in excluded_keys:
                continue
            for leg_position in leg_positions:
                leg_position[key] = value
        return

    if not hasattr(ctp_position, "__dict__"):
        return

    for key in dir(ctp_position):
        if key.startswith("_") or key in excluded_keys:
            continue
        try:
            value = getattr(ctp_position, key, None)
        except Exception:
            continue
        if value is None or callable(value):
            continue
        for leg_position in leg_positions:
            leg_position[key] = value

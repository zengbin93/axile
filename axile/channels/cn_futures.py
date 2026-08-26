"""国内期货渠道共用的合约身份与手数量化.

郑商所四位年份代码（``TA2701`` / ``TA2701C5000``）与持仓三位代码
（``TA701`` / ``TA701C5000``）是同一张合约。只按 CZCE 品种表压缩年份，
避免把 ``rb2610``、``cu2606C69000`` 误压。
"""

from __future__ import annotations

import re
from datetime import datetime

from axile.executor.ctp_product_sessions import CTP_PRODUCT_SESSIONS

# 期货 TA2701；期权 TA2701C5000（郑商所无 -C- 分隔符）。
_CZCE_CONTRACT = re.compile(r"^(?:CZCE\.)?(?P<product>[A-Za-z]+)(?P<year>\d{2})(?P<month>\d{2})(?P<option>[CP]\d+)?$")
_CZCE_NATIVE_OPTION = re.compile(r"^[A-Za-z]+\d{3}[CP]\d+$")
_CZCE_PRODUCTS = frozenset(product for exchange, product in CTP_PRODUCT_SESSIONS if exchange == "CZCE")


def czce_is_option_instrument(symbol: str) -> bool:
    """判断已压缩的郑商所代码是否为期权（``TA701C5000``）."""
    local = symbol.split(".", 1)[-1]
    match = _CZCE_NATIVE_OPTION.fullmatch(local)
    if match is None:
        return False
    product = re.match(r"[A-Za-z]+", local)
    return bool(product and product.group(0) in _CZCE_PRODUCTS)


def canonicalize_cn_futures_symbol(symbol: str, *, reference_year: int | None = None) -> str:
    """
    把郑商所四位年份期货/期权代码收成与持仓一致的三位年代码.

    Parameters
    ----------
    symbol : str
        策略或持仓代码；非郑商所四位年合约原样返回。
    reference_year : int | None, optional
        判定「最近一个同个位年份」的参照年；缺省为当前年。

    Returns
    -------
    str
        可与天勤/CTP 持仓 ``instrument_id`` 对齐的代码。
    """
    match = _CZCE_CONTRACT.fullmatch(symbol)
    if match is None:
        return symbol
    product = match.group("product")
    if product not in _CZCE_PRODUCTS:
        return symbol
    requested_year = 2000 + int(match.group("year"))
    year = reference_year if reference_year is not None else datetime.now().year
    native_digit = requested_year % 10
    nearest_year = min(
        (candidate for candidate in range(2000, 2100) if candidate % 10 == native_digit),
        key=lambda candidate: abs(candidate - year),
    )
    if requested_year != nearest_year:
        return symbol
    option = match.group("option") or ""
    return f"{product}{match.group('year')[-1]}{match.group('month')}{option}"


def quantize_cn_futures_quantity(weight: float, equity: float, notional_per_unit: float) -> float:
    """
    按国内期货执行器口径把目标权重截成整数手.

    Parameters
    ----------
    weight : float
        带符号目标权重。
    equity : float
        账户总权益。
    notional_per_unit : float
        一手名义（``|市值| / 手数``，即价格 × 合约乘数）。

    Returns
    -------
    float
        向零截断后的目标手数；名义无效时为 0。
    """
    if notional_per_unit <= 0:
        return 0.0
    return float(int(equity * weight / notional_per_unit))

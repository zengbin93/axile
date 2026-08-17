"""预留的人工介入交易相关的工具函数."""

from collections.abc import Mapping, Sequence

import pandas as pd
from loguru import logger


def _parse_human_position(pos: Mapping[str, object]) -> tuple[str, float, pd.Timestamp] | None:
    """解析单个手工持仓配置."""
    assert all(k in pos for k in ("symbol", "weight", "expire_time")), (
        "手工持仓配置必须包含 'symbol'、'weight' 和 'expire_time' 字段"
    )

    symbol = pos["symbol"]
    if not isinstance(symbol, str):
        return None

    try:
        expire_time = pd.to_datetime(pos["expire_time"])
    except Exception:
        return None

    weight_obj = pos["weight"]
    try:
        weight = float(weight_obj) if weight_obj is not None else 0.0
    except (ValueError, TypeError):
        return None

    return symbol, weight, expire_time


def apply_human_positions(
    target: dict[str, float],
    human_positions: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, float]:
    """将手工交易的仓位强制覆盖到 target 中.

    human_positions 设置样例如下：
        hp = [
            {"symbol": "159351.SZ", "weight": 0.2, "expire_time": "2025-11-01 14:00"},
            {"symbol": "600400.SH", "weight": 0.0, "expire_time": "2025-11-08 14:00"}
        ]

    其中，symbol 表示要持仓的品种，weight 表示相对于账户总资金的持仓权重，expire_time 表示仓位设定的过期时间，仓位过期后将自动平仓。
    """
    if not human_positions:
        return target

    now_ = pd.to_datetime("now")
    new_target = target.copy()

    # 将 hp 中没有过期的仓位覆盖写入 new_target
    for pos in human_positions:
        parsed = _parse_human_position(pos)
        if not parsed:
            continue

        symbol, weight, expire_time = parsed

        # 检查仓位是否未过期
        if now_ <= expire_time:
            new_target[symbol] = weight
            logger.info(f"手工仓位覆盖 (过期时间: {expire_time}): {symbol} = {weight} ")
        else:
            if symbol not in new_target:
                logger.warning(f"手工仓位已过期 (过期时间: {expire_time})，且不在 target 中，平仓: {symbol} = 0")
                new_target[symbol] = 0
            else:
                logger.warning(
                    f"手工仓位已过期 (过期时间: {expire_time})，执行target中的仓位: {symbol} = {new_target[symbol]}"
                )

    return new_target


def apply_symbol_constraint(
    target: dict[str, float],
    constraints: Mapping[str, Mapping[str, float | None]],
) -> dict[str, float]:
    """根据品种约束条件调整仓位.

    Example:
        target = {"600400.SH": 0.05, "159351.SZ": 0.8}
        sc = {
            "600400.SH": {"long_leverage": 1, "short_leverage": 0, "min_abs_weight": 0}
        }

        new_target = apply_symbol_constraint(target, sc)

    其中：
    - min_abs_weight 表示该品种的最小持仓绝对值（不管方向）。
    - long_leverage: 多头杠杆乘数。例如 1 表示多头一倍杠杆, 2 表示两倍杠杆; 0 表示禁止做多。
    - short_leverage: 空头杠杆乘数。例如 1 表示空头一倍杠杆, 2 表示两倍杠杆; 0 表示禁止做空。

    逻辑顺序：
    1. 先用 long_leverage 和 short_leverage 按杠杆调整仓位
    2. 再用 min_abs_weight 调整仓位至最小值（如果当前仓位绝对值小于该值）

    :param target: 原始目标仓位字典，格式如 {"600400.SH": 0.2, "159351.SZ": 0.4}
    :param constraints: 品种约束字典，格式如上所示
    :return: 调整后的目标仓位字典
    """
    new_target = target.copy()

    for symbol, cons in constraints.items():
        min_abs_wt = cons.get("min_abs_weight", 0)
        long_lev = cons.get("long_leverage", 1)
        short_lev = cons.get("short_leverage", 1)

        # 获取当前权重，如果不在 target 中则为 0
        wt = new_target.get(symbol, 0.0)
        original_wt = wt

        if long_lev is not None and wt > 0:
            wt = wt * long_lev
            logger.info(f"调整仓位: {symbol} 从 {original_wt} 调整到 {wt} 根据 long_leverage {long_lev}")

        if short_lev is not None and wt < 0:
            wt = wt * short_lev
            logger.info(f"调整仓位: {symbol} 从 {original_wt} 调整到 {wt} 根据 short_leverage {short_lev}")

        if wt != 0 and (min_abs_wt is not None) and (abs(wt) < min_abs_wt):
            logger.info(f"调整仓位: {symbol} 从 {wt} 提升到最小绝对值 {min_abs_wt}")
            wt = min_abs_wt if wt > 0 else -min_abs_wt

        if wt != original_wt:
            logger.warning(f"仓位变化: {symbol} 从 {original_wt} 调整到 {wt}")
            new_target[symbol] = wt

    return new_target

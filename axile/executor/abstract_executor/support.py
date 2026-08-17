"""`AbstractExecutor` 模块内部使用的私有辅助函数.

本文件只放轻量的类型收敛与字典规范化工具，
供 execution、facade 等子模块复用。
"""

type ObjectDict = dict[str, object]
type TradeRules = dict[str, ObjectDict]


def _coerce_object_dict(value: object) -> ObjectDict:
    """
    将任意字典值收敛为 ``dict[str, object]``.

    Parameters
    ----------
    value : object
        待收敛的原始对象。

    Returns
    -------
    ObjectDict
        规范化后的对象字典；无法转换时返回空字典。
    """
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _coerce_trade_rules(value: object) -> TradeRules:
    """
    将任意交易规则值收敛为按品种索引的规则字典.

    Parameters
    ----------
    value : object
        待收敛的原始交易规则对象。

    Returns
    -------
    TradeRules
        规范化后的交易规则映射。
    """
    if not isinstance(value, dict):
        return {}
    return {str(symbol): _coerce_object_dict(rule) for symbol, rule in value.items()}


def _coerce_int(value: object) -> int | None:
    """
    将常见整型输入安全收敛为 ``int``.

    Parameters
    ----------
    value : object
        待收敛的原始对象。

    Returns
    -------
    int | None
        转换成功时返回整数，否则返回 ``None``。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None

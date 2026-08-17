"""提供证券代码到掘金量化命名规则的转换辅助函数."""


def to_gm_symbol(symbol: str) -> str:
    """
    将 Tushare 股票代码转换为掘金量化（GM）格式.

    Parameters
    ----------
    symbol : str
        Tushare 格式的股票代码，格式为 ``代码.交易所``，例如 ``600000.SH``。

    Returns
    -------
    str
        掘金量化格式的股票代码，格式为 ``交易所代码.股票代码``，
        例如 ``SHSE.600000``。

    Raises
    ------
    ValueError
        输入格式不合法，或交易所后缀不受支持时抛出。

    Notes
    -----
    转换规则如下：

    - ``SH`` -> ``SHSE``（上证）
    - ``SZ`` -> ``SZSE``（深证）

    调用方通常会把 ``ValueError`` 视作用户输入错误，因此这里仅对输入格式与
    不支持的交易所后缀抛出 ``ValueError``，不再额外包装其他异常层级。
    """
    exchange_map = {
        "SH": "SHSE",
        "SZ": "SZSE",
    }

    try:
        code_part, exchange_suffix = symbol.split(".")
    except ValueError as exc:
        raise ValueError(f"股票代码格式错误: {symbol}，预期格式为 代码.交易所。") from exc

    gm_exchange = exchange_map.get(exchange_suffix)
    if gm_exchange is None:
        raise ValueError(f"不支持的交易所后缀: {exchange_suffix}，输入格式: {symbol}")

    return f"{gm_exchange}.{code_part}"

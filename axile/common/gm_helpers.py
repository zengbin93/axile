"""提供证券代码到掘金量化命名规则的转换辅助函数."""


def to_gm_symbol(symbol: str) -> str:
    """
    将 Axile 或 GM 股票代码转换为掘金量化（GM）格式.

    Parameters
    ----------
    symbol : str
        Tushare 格式 ``代码.交易所`` 或 GM 格式 ``交易所.代码``，
        例如 ``600000.SH`` 或 ``SHSE.600000``。

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
    - ``BJ`` -> ``BJSE``（北证）

    调用方通常会把 ``ValueError`` 视作用户输入错误，因此这里仅对输入格式与
    不支持的交易所后缀抛出 ``ValueError``，不再额外包装其他异常层级。
    """
    from axile.common.gm_symbols import GM_SYMBOL_RESOLVER

    return GM_SYMBOL_RESOLVER.to_gm(symbol)

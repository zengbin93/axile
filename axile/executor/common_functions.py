"""
交易执行器公共函数模块.

抽取各渠道重复的核心业务逻辑，提供统一、可复用的工具函数.

使用示例：
    from axile.executor.common_functions import is_trading_time

    # 检查是否为交易时间
    if is_trading_time():
        execute_trading()
"""


def is_trading_time() -> bool:
    """
    统一的交易时间检查函数.

    支持A股市场的标准交易时间：
    - 上午：09:30 - 11:30
    - 下午：13:00 - 15:00
    - 周末不交易

    这个函数统一了各个执行器中的交易时间检查逻辑。

    Returns
    -------
        bool: True表示当前是交易时间，False表示不是交易时间

    Examples
    --------
        >>> # 在交易时间内
        >>> result = is_trading_time()  # 返回True或False取决于当前时间
    """
    import pandas as pd

    now_time = pd.Timestamp.now()
    now_time_hm = now_time.strftime("%H:%M")

    # 检查是否为周末
    if now_time.weekday() >= 5:  # 5=周六, 6=周日
        return False

    # 检查是否在交易时间内（A股分段交易时间）
    if "09:30" <= now_time_hm <= "11:30":
        return True
    if "13:00" <= now_time_hm <= "15:00":
        return True

    return False


if __name__ == "__main__":
    # 测试 is_trading_time
    print("当前是否为交易时间:", is_trading_time())

    # 测试完成
    print("✅ common_functions.py 模块测试完成")

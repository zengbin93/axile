"""自定义组合函数的目标权重计算入口."""

from axile.server.sandbox import ScriptResult, run_portfolio_script, snapshot_context


def calculate_portfolio_target(code: str, context: object | None) -> ScriptResult:
    """
    在隔离子进程中执行组合函数.

    Parameters
    ----------
    code : str
        定义 ``calculate_portfolio(context)`` 的 Python 源码。
    context : object | None
        真实账户上下文或样例上下文。

    Returns
    -------
    ScriptResult
        脚本执行结果及结构化错误。
    """
    return run_portfolio_script(code, snapshot_context(context))

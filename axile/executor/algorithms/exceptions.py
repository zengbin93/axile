"""算法模块共享的异常处理辅助工具."""


class SubMinQuantityError(ValueError):
    """下单数量按交易所步长取整后 ``<= 0``（或不足最小下单量）时抛出.

    用于渠道在提交前拦截「注定被交易所拒绝」的碎量单，
    交由上层按「跳过该品种」而非「下单失败」处理。继承 ``ValueError`` 以天然落入
    ``RECOVERABLE_ALGORITHM_EXCEPTIONS``，即便某些调用路径未显式捕获也不会中断整轮执行。
    """


RECOVERABLE_ALGORITHM_EXCEPTIONS: tuple[type[BaseException], ...] = (
    RuntimeError,
    ValueError,
    TypeError,
    OSError,
)


def format_exception_message(exc: BaseException) -> str:
    """生成适合日志与 memory 记录的异常消息."""
    return f"{type(exc).__name__}: {exc}"

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


def execution_error_message(exc: BaseException, operation: str = "执行") -> str:
    """只回放渠道在错误发生处给出的说明，未知异常使用操作级中文。"""
    message = getattr(exc, "execution_error", None)
    if isinstance(message, str) and message:
        return message
    if isinstance(exc, TimeoutError):
        return "报单请求超时，是否受理尚未确认" if operation == "报单" else f"{operation}超时，结果尚未确认"
    return f"{operation}失败，具体原因未确认"

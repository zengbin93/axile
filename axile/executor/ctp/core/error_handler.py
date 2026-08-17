"""CTP错误处理模块."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar, cast

import loguru

P = ParamSpec("P")
R = TypeVar("R")

# 这里只兜住 CTP 回调常见的 Python 侧异常，让退出信号等非业务异常继续上抛。
CTP_COMMON_EXCEPTIONS = (
    AttributeError,
    KeyError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def handle_ctp_error(
    func: Callable[Concatenate[object, P], R],
) -> Callable[Concatenate[object, P], R]:
    """
    为 CTP 调用添加流控错误重试.

    Parameters
    ----------
    func : Callable[Concatenate[object, P], R]
        需要包装的实例方法。

    Returns
    -------
    Callable[Concatenate[object, P], R]
        带有流控重试逻辑的新方法。

    Notes
    -----
    仅当错误信息表明遇到 CTP 4097 流控限制时才会重试，其他异常直接抛出，
    避免把真正的业务错误误判为可恢复故障。
    """

    @wraps(func)
    def wrapper(self: object, *args: P.args, **kwargs: P.kwargs) -> R:
        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                error_msg = str(e)

                if "4097" in error_msg or "流控" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2**attempt)
                        loguru.logger.warning(
                            f"检测到CTP流控错误，{wait_time}秒后重试 (尝试 {attempt + 1}/{max_retries})"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        loguru.logger.error(f"CTP流控错误重试失败，已达最大重试次数: {error_msg}")
                        raise
                else:
                    raise

        raise RuntimeError("CTP错误处理器异常结束")

    return cast("Callable[Concatenate[object, P], R]", wrapper)


def safe_callback(
    logger: loguru.Logger | None = None,
    log_traceback: bool = True,
    default_return: R = None,  # type: ignore[assignment]
) -> Callable[[Callable[Concatenate[object, P], R]], Callable[Concatenate[object, P], R]]:
    """
    装饰器：安全执行 CTP 回调方法并记录异常.

    用于替代回调方法中重复的 try-except 块，减少样板代码。

    Parameters
    ----------
    logger : loguru.Logger | None, optional
        日志记录器；为 ``None`` 时优先使用实例上的 ``logger``，否则回退到 ``loguru.logger``。
    log_traceback : bool, default=True
        是否记录完整异常堆栈。
    default_return : R, optional
        回调执行异常时的默认返回值。

    Examples
    --------
    >>> @safe_callback(log_traceback=True)
    ... def OnRspOrderAction(self, pInputOrderAction, pRspInfo, _nRequestID, _bIsLast):
    ...     ...
    """

    def decorator(func: Callable[Concatenate[object, P], R]) -> Callable[Concatenate[object, P], R]:
        @wraps(func)
        def wrapper(self: object, *args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return func(self, *args, **kwargs)
            except CTP_COMMON_EXCEPTIONS as e:
                log = logger or getattr(self, "logger", loguru.logger)
                method_name = func.__name__
                log.error(f"❌ {method_name} 执行异常: {e}")
                if log_traceback:
                    log.error(f"异常详情: {traceback.format_exc()}")
                return default_return  # type: ignore[return-value]

        return cast("Callable[Concatenate[object, P], R]", wrapper)

    return decorator


def import_time() -> float:
    """返回模块导入时间，用于避免循环导入问题."""
    return time.time()

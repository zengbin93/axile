"""
QMT 客户端启动与初始化辅助函数.

包含桌面端窗口探测、启动登录、就绪等待和 XtQuantTrader 初始化逻辑。
"""

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
# pyright: reportReturnType=false
# pyright: reportMissingTypeStubs=false
# pyright: reportMissingModuleSource=false

import random
import subprocess
import time
from pathlib import Path
from typing import Protocol, cast

import loguru
import pyautogui
import pygetwindow  # type: ignore
from xtquant import xtdata  # type: ignore
from xtquant.xttrader import XtQuantTrader  # type: ignore
from xtquant.xttype import StockAccount  # type: ignore

from axile.executor.algorithms.core.base import LoggerProtocol
from axile.executor.qmt.core.qmt_callback import QMTTraderCallback


class _WindowProtocol(Protocol):
    """QMT 辅助函数使用的最小桌面窗口协议."""

    def activate(self) -> object:
        pass

    def close(self) -> object:
        pass


def find_exe_window(title: str, **kwargs: object) -> _WindowProtocol | None:
    """
    在 Windows 系统下按标题查找窗口.

    Parameters
    ----------
    title : str
        目标窗口标题。
    **kwargs : object
        额外参数；支持通过 ``logger`` 传入日志对象。

    Returns
    -------
    _WindowProtocol | None
        命中的窗口对象；未找到或找到多个时返回 ``None``。
    """
    logger = cast(LoggerProtocol, kwargs.get("logger", loguru.logger))

    try:
        windows = pygetwindow.getWindowsWithTitle(title)  # type: ignore[attr-defined]
        if len(windows) > 1:
            logger.warning(f"找到多个 {title} 窗口，数量：{len(windows)}；请检查是否有多个程序实例")
            return None
        if len(windows) == 0:
            logger.warning(f"未找到 {title} 窗口")
            return None
        return cast(_WindowProtocol, windows[0])
    except Exception as e:
        logger.error(f"Error finding window: {e}")
        return None


def close_exe_window(title: str, **kwargs: object) -> None:
    """
    在 Windows 系统下关闭指定 exe 应用窗口.

    Parameters
    ----------
    title : str
        程序标题，支持模糊匹配，不要求完全一致。
    **kwargs : object
        额外参数；支持通过 ``logger`` 传入日志对象。
    """
    logger = cast(LoggerProtocol, kwargs.get("logger", loguru.logger))

    window = find_exe_window(title)
    if window:
        qmt_window = cast(_WindowProtocol, window)
        qmt_window.activate()
        qmt_window.close()
        pyautogui.press("enter")
    else:
        logger.error(f"没有找到 {title} 程序")


def wait_qmt_ready(timeout: int = 60, **kwargs: object) -> bool:
    """
    等待 QMT 行情接口就绪.

    Parameters
    ----------
    timeout : int, default=60
        最大等待时间，单位为秒。
    **kwargs : object
        额外参数；支持通过 ``logger`` 传入日志对象。

    Returns
    -------
    bool
        在超时前检测到行情接口可用时返回 ``True``。
    """
    logger = cast(LoggerProtocol, kwargs.get("logger", loguru.logger))
    start = time.time()
    while time.time() - start < timeout:
        x = xtdata.get_full_tick(code_list=["000001.SZ"])
        if x and x["000001.SZ"]["lastPrice"] > 0:
            return True

        logger.warning("等待 QMT 窗口就绪")
        time.sleep(1)
    return False


def initialize_qmt(callback: QMTTraderCallback | None = None, **kwargs: object) -> tuple[XtQuantTrader, StockAccount]:
    """
    初始化 QMT 交易端.

    Parameters
    ----------
    callback : QMTTraderCallback | None, default=None
        可选的回调处理器实例。
    **kwargs : object
        初始化参数，支持 ``mini_qmt_dir``、``account_id``、``session_id`` 和 ``logger``。

    Returns
    -------
    tuple[XtQuantTrader, StockAccount]
        初始化完成的 ``XtQuantTrader`` 实例与 ``StockAccount`` 对象。

    Raises
    ------
    ValueError
        当关键初始化参数缺失或格式不正确时抛出。
    AssertionError
        当交易连接或账号订阅失败时抛出。
    """
    logger = cast(LoggerProtocol, kwargs.get("logger", loguru.logger))

    mini_qmt_dir = kwargs.get("mini_qmt_dir")
    account_id = kwargs.get("account_id")
    session_id = kwargs.get("session_id", random.randint(10000, 20000))

    if mini_qmt_dir is None:
        raise ValueError("mini_qmt_dir parameter is required")
    if account_id is None:
        raise ValueError("account_id parameter is required")
    if not isinstance(account_id, str):
        raise ValueError("account_id must be a string")

    xtt = XtQuantTrader(mini_qmt_dir, session=session_id)
    acc = StockAccount(account_id, "STOCK")  # type: ignore[assignment]

    if isinstance(acc, str):
        raise ValueError(f"Failed to create StockAccount: {acc}")

    if callback is not None:
        xtt.register_callback(callback)
        logger.info("已注册 QMT 回调处理器")

    xtt.start()
    xtt.connect()
    assert xtt.connected, "交易服务器连接失败"
    _res = xtt.subscribe(acc)
    assert _res == 0, "账号订阅失败"

    xtdata.data_dir = str(Path(mini_qmt_dir) / "datadir")  # type: ignore[assignment]
    xtdata.reconnect()
    logger.warning(f"xtdata 数据路径：{xtdata.data_dir}")
    return xtt, acc


def start_qmt_exe(acc: str, pwd: str, qmt_exe: str, title: str, max_retry: int = 6, **kwargs: object) -> None:
    r"""
    在 Windows 系统下启动 QMT 并完成登录.

    Parameters
    ----------
    acc : str
        QMT 账号。
    pwd : str
        QMT 密码。
    qmt_exe : str
        QMT 应用路径，例如 ``D:\\国金证券QMT交易端\\bin.x64\\XtItClient.exe``。
    title : str
        QMT 窗口标题。
    max_retry : int, default=6
        最大重试次数。
    **kwargs : object
        额外参数；支持 ``wait_seconds`` 和 ``logger``。

    Raises
    ------
    RuntimeError
        当 QMT 连续多次尝试后仍无法成功启动时抛出。
    """
    logger = cast(LoggerProtocol, kwargs.get("logger", loguru.logger))
    wait_seconds_raw = kwargs.get("wait_seconds", 6)
    wait_seconds = float(wait_seconds_raw) if isinstance(wait_seconds_raw, (int, float)) else 6.0
    i = 0
    while not find_exe_window(title):
        if i > max_retry:
            logger.error(f"QMT连续{i}次尝试依旧无法启动")
            raise RuntimeError(f"QMT桌面端启动失败 - 账户: {acc}")

        close_exe_window(title)

        i += 1
        try:
            subprocess.Popen(qmt_exe)
            time.sleep(wait_seconds)

            qmt_windows = find_exe_window(title)
            if not qmt_windows:
                continue

            qmt_window = cast(_WindowProtocol, qmt_windows)
            qmt_window.activate()
            pyautogui.typewrite(acc)
            pyautogui.press("tab")
            pyautogui.typewrite(pwd)
            pyautogui.press("enter")
            qmt_window.activate()
            time.sleep(wait_seconds)

        except Exception as e:
            logger.exception(f"启动QMT失败：{e}")

    if find_exe_window(title):
        logger.info(f"启动 QMT 成功，账号：{acc}")
    else:
        logger.error(f"启动 QMT 失败，账号：{acc}")
        raise RuntimeError(f"QMT桌面端启动失败 - 账户: {acc}")

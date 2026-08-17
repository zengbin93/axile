"""QMT 测试辅助函数：在缺少真实 xtquant SDK 的环境中提供最小占位模块。"""

from __future__ import annotations

import sys
from types import ModuleType


def install_qmt_stubs() -> None:
    """向 ``sys.modules`` 注册 QMT 相关依赖的最小占位实现，供测试导入 QMT 模块使用。"""
    pyautogui_module = sys.modules.setdefault("pyautogui", ModuleType("pyautogui"))
    pygetwindow_module = sys.modules.setdefault("pygetwindow", ModuleType("pygetwindow"))
    xtquant_module = sys.modules.setdefault("xtquant", ModuleType("xtquant"))
    xtdata_module = sys.modules.setdefault("xtquant.xtdata", ModuleType("xtquant.xtdata"))
    xttrader_module = sys.modules.setdefault("xtquant.xttrader", ModuleType("xtquant.xttrader"))
    xttype_module = sys.modules.setdefault("xtquant.xttype", ModuleType("xtquant.xttype"))

    pyautogui_module.press = lambda *_args, **_kwargs: None
    pyautogui_module.typewrite = lambda *_args, **_kwargs: None
    pygetwindow_module.getWindowsWithTitle = lambda *_args, **_kwargs: []

    xtdata_module.data_dir = ""
    xtdata_module.get_full_tick = lambda *_args, **_kwargs: {}
    xtdata_module.reconnect = lambda *_args, **_kwargs: None

    class XtQuantTrader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.connected = False

        def register_callback(self, _callback: object) -> None:
            pass

        def start(self) -> None:
            self.connected = True

        def connect(self) -> None:
            self.connected = True

        def subscribe(self, _acc: object) -> int:
            return 0

    class XtQuantTraderCallback:
        pass

    class StockAccount:
        def __init__(self, account_id: str, account_type: str) -> None:
            self.account_id = account_id
            self.account_type = account_type

    class XtAsset:
        pass

    class XtOrder:
        pass

    class XtPosition:
        pass

    class XtTrade:
        pass

    class XtOrderError:
        pass

    class XtCancelError:
        pass

    xttrader_module.XtQuantTrader = XtQuantTrader
    xttrader_module.XtQuantTraderCallback = XtQuantTraderCallback
    xttype_module.StockAccount = StockAccount
    xttype_module.XtAsset = XtAsset
    xttype_module.XtOrder = XtOrder
    xttype_module.XtPosition = XtPosition
    xttype_module.XtTrade = XtTrade
    xttype_module.XtOrderError = XtOrderError
    xttype_module.XtCancelError = XtCancelError
    xtquant_module.xtdata = xtdata_module

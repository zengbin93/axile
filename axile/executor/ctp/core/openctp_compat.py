"""为可选的 ``openctp_ctp`` 导入提供兼容辅助.

CTP 运行时依赖 ``openctp_ctp`` 提供的原生绑定。
由于仓库中的大多数单元测试只覆盖纯 Python 逻辑，这些绑定在默认情况下是可选的。
因此本模块默认暴露轻量占位实现，只有在显式请求真实 CTP 连接时才导入原生扩展。
"""

from __future__ import annotations

import locale
import os
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

_LOCALE_ENV_VARS = ("LC_ALL", "LC_CTYPE", "LANG")
_LOCALE_FALLBACKS = ("C.UTF-8", "C")


def _ensure_valid_process_locale() -> None:
    """在导入原生 OpenCTP 绑定前规范化进程 locale."""
    # 原生扩展在部分系统 locale 配置下会在导入阶段直接失败，因此先尽量把进程切到稳定编码环境。
    try:
        locale.setlocale(locale.LC_CTYPE, "")
        return
    except locale.Error:
        pass

    for candidate in _LOCALE_FALLBACKS:
        for env_name in _LOCALE_ENV_VARS:
            os.environ[env_name] = candidate
        try:
            locale.setlocale(locale.LC_CTYPE, candidate)
            return
        except locale.Error:
            continue

    try:
        locale.setlocale(locale.LC_CTYPE, "C")
    except locale.Error:
        return


def _missing_openctp_message() -> str:
    return (
        "openctp_ctp is required for live CTP connectivity. Install the optional dependency with `uv sync --extra ctp`."
    )


def _raise_missing_openctp() -> None:
    raise ModuleNotFoundError(_missing_openctp_message())


class _PlaceholderStruct:
    """在测试中支持属性赋值的回退结构体类型."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        _ = args
        for key, value in kwargs.items():
            setattr(self, key, value)


class _PlaceholderMdApi:
    """回退版行情 API 类."""

    @staticmethod
    def CreateFtdcMdApi(_flow_path: str) -> "_PlaceholderMdApi":
        _raise_missing_openctp()


class _PlaceholderTraderApi:
    """回退版交易 API 类."""

    @staticmethod
    def CreateFtdcTraderApi(_flow_path: str) -> "_PlaceholderTraderApi":
        _raise_missing_openctp()


class _PlaceholderMdSpi:
    """回退版行情 SPI 基类."""


class _PlaceholderTraderSpi:
    """回退版交易 SPI 基类."""


_PLACEHOLDER_MDAPI_NAMESPACE = SimpleNamespace(CThostFtdcReqUserLoginField=_PlaceholderStruct)
_PLACEHOLDER_TRADER_SYMBOLS = {
    "THOST_FTDC_TC_GFD": "3",
    "THOST_FTDC_VC_AV": "1",
    "THOST_TERT_QUICK": "2",
    "THOST_FTDC_AF_Delete": "0",
    "THOST_FTDC_CC_Immediately": "1",
    "THOST_FTDC_D_Buy": "0",
    "THOST_FTDC_D_Sell": "1",
    "THOST_FTDC_FCC_NotForceClose": "0",
    "THOST_FTDC_HF_Speculation": "1",
    "THOST_FTDC_OF_Close": "1",
    "THOST_FTDC_OF_CloseToday": "3",
    "THOST_FTDC_OF_CloseYesterday": "4",
    "THOST_FTDC_OF_Open": "0",
    "THOST_FTDC_OPT_LimitPrice": "2",
    # 期权行权 / 放弃 / 自对冲指令的标志位（CTP ExecOrder 协议）
    "THOST_FTDC_AT_Execute": "1",  # 行权
    "THOST_FTDC_AT_Abandon": "0",  # 放弃
    "THOST_FTDC_OCF_CloseSelfOptionPosition": "1",  # 自对冲：平掉自己持有的期权
    "THOST_FTDC_OCF_ReserveOptionPosition": "0",
    "CThostFtdcInputExecOrderActionField": _PlaceholderStruct,
    "CThostFtdcInputExecOrderField": _PlaceholderStruct,
    # 自对冲专用结构体（ReqOptionSelfCloseInsert / ReqOptionSelfCloseAction）
    "CThostFtdcInputOptionSelfCloseActionField": _PlaceholderStruct,
    "CThostFtdcInputOptionSelfCloseField": _PlaceholderStruct,
    "CThostFtdcInputOrderActionField": _PlaceholderStruct,
    "CThostFtdcInputOrderField": _PlaceholderStruct,
    "CThostFtdcInvestorPositionField": _PlaceholderStruct,
    "CThostFtdcQryInstrumentField": _PlaceholderStruct,
    "CThostFtdcQryInvestorPositionField": _PlaceholderStruct,
    "CThostFtdcQryOrderField": _PlaceholderStruct,
    "CThostFtdcQrySettlementInfoField": _PlaceholderStruct,
    "CThostFtdcQryTradeField": _PlaceholderStruct,
    "CThostFtdcQryTradingAccountField": _PlaceholderStruct,
    "CThostFtdcReqAuthenticateField": _PlaceholderStruct,
    "CThostFtdcReqUserLoginField": _PlaceholderStruct,
    "CThostFtdcSettlementInfoConfirmField": _PlaceholderStruct,
    "CThostFtdcTraderApi": _PlaceholderTraderApi,
    "CThostFtdcTraderSpi": _PlaceholderTraderSpi,
    "CThostFtdcUserSystemInfoField": _PlaceholderStruct,
}

_OPENCTP_MD_MODULE: ModuleType | None = None
_OPENCTP_TRADER_MODULE: ModuleType | None = None

OPENCTP_AVAILABLE = False


def ensure_openctp_loaded() -> None:
    """
    按需导入原生 OpenCTP 绑定.

    Notes
    -----
    该函数只在第一次真正访问原生能力时触发导入，保证纯 Python 单元测试
    不需要安装 ``openctp_ctp`` 也能覆盖上层业务逻辑。
    """
    global OPENCTP_AVAILABLE, _OPENCTP_MD_MODULE, _OPENCTP_TRADER_MODULE

    if OPENCTP_AVAILABLE:
        return

    _ensure_valid_process_locale()

    try:
        from openctp_ctp import thostmduserapi as md_module  # type: ignore[import-not-found]
        from openctp_ctp import thosttraderapi as trader_module  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(_missing_openctp_message()) from exc

    _OPENCTP_MD_MODULE = md_module
    _OPENCTP_TRADER_MODULE = trader_module
    OPENCTP_AVAILABLE = True


def _resolve_md_symbol(name: str, fallback: object) -> object:
    if _OPENCTP_MD_MODULE is None:
        return fallback
    return getattr(_OPENCTP_MD_MODULE, name)


def _resolve_trader_symbol(name: str, fallback: object) -> object:
    if _OPENCTP_TRADER_MODULE is None:
        return fallback
    return getattr(_OPENCTP_TRADER_MODULE, name)


class _LazyNamespaceProxy:
    """
    暴露模块式代理，并在原生模块加载后自动切换目标.

    Notes
    -----
    这让调用方可以在 import 阶段直接拿到 ``mdapi``，而不必显式关心
    OpenCTP 是否已经完成延迟加载。
    """

    def __init__(self, resolver: Callable[[], object], fallback: object) -> None:
        self._resolver = resolver
        self._fallback = fallback

    def _target(self) -> object:
        target = self._resolver()
        return target if target is not None else self._fallback

    def __getattr__(self, name: str) -> object:
        return getattr(self._target(), name)


class _LazySymbolProxy:
    """
    代理单个符号，使延迟加载后的引用保持稳定.

    Notes
    -----
    代理对象同时实现 ``__call__``、``__getattr__`` 和 ``__mro_entries__``，
    这样无论调用方把它当成构造器、常量还是基类占位符，都可以在原生绑定
    可用后无缝切换到真实实现。
    """

    def __init__(self, resolver: Callable[[], object], fallback: object) -> None:
        self._resolver = resolver
        self._fallback = fallback

    def _target(self) -> object:
        target = self._resolver()
        return target if target is not None else self._fallback

    def __call__(self, *args: object, **kwargs: object) -> object:
        target = self._target()
        return target(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._target(), name)

    def __mro_entries__(self, _bases: tuple[type[Any], ...]) -> tuple[type[Any], ...]:
        target = self._target()
        if isinstance(target, type):
            return (target,)
        if isinstance(self._fallback, type):
            return (self._fallback,)
        return ()


def _build_spi_proxy(base_cls: type[object], target: object) -> object:
    """
    构建把原生 SPI 回调转发到 Python 对象的适配器.

    Parameters
    ----------
    base_cls : type[object]
        原生 OpenCTP SPI 基类。
    target : object
        实际承接 ``On*`` 回调的 Python 对象。

    Returns
    -------
    object
        可注册给原生 API 的 SPI 实例。
    """

    def _make_forwarder(name: str):
        def _forward(self, *args: object, **kwargs: object) -> object:
            return getattr(self._wrapped, name)(*args, **kwargs)

        _forward.__name__ = name
        return _forward

    class _ForwardingSpi(base_cls):
        def __init__(self, wrapped: object) -> None:
            super().__init__()
            self._wrapped = wrapped

    # 仅为目标对象当前实现的 ``On*`` 方法生成转发器，避免暴露大量永远不会处理的空回调。
    callback_methods: dict[str, object] = {
        name: _make_forwarder(name)
        for name in dir(target)
        if name.startswith("On") and callable(getattr(target, name, None))
    }

    for name, func in callback_methods.items():
        setattr(_ForwardingSpi, name, func)

    return _ForwardingSpi(target)


def create_md_spi_proxy(target: object) -> object:
    """
    为 Python 目标对象构建原生行情 SPI 包装器.

    Parameters
    ----------
    target : object
        实际处理行情回调的 Python 对象。

    Returns
    -------
    object
        可传给 ``RegisterSpi`` 的原生 SPI 包装器。
    """
    ensure_openctp_loaded()
    base_cls = _resolve_md_symbol("CThostFtdcMdSpi", _PlaceholderMdSpi)
    if not isinstance(base_cls, type):
        raise RuntimeError("Failed to resolve CThostFtdcMdSpi")
    return _build_spi_proxy(base_cls, target)


def create_trader_spi_proxy(target: object) -> object:
    """
    为 Python 目标对象构建原生交易 SPI 包装器.

    Parameters
    ----------
    target : object
        实际处理交易回调的 Python 对象。

    Returns
    -------
    object
        可传给 ``RegisterSpi`` 的原生 SPI 包装器。
    """
    ensure_openctp_loaded()
    base_cls = _resolve_trader_symbol("CThostFtdcTraderSpi", _PlaceholderTraderSpi)
    if not isinstance(base_cls, type):
        raise RuntimeError("Failed to resolve CThostFtdcTraderSpi")
    return _build_spi_proxy(base_cls, target)


mdapi = _LazyNamespaceProxy(lambda: _OPENCTP_MD_MODULE, _PLACEHOLDER_MDAPI_NAMESPACE)

CThostFtdcMdApi = _LazySymbolProxy(
    lambda: _resolve_md_symbol("CThostFtdcMdApi", _PlaceholderMdApi),
    _PlaceholderMdApi,
)
CThostFtdcMdSpi = _LazySymbolProxy(
    lambda: _resolve_md_symbol("CThostFtdcMdSpi", _PlaceholderMdSpi),
    _PlaceholderMdSpi,
)

THOST_FTDC_TC_GFD = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_TC_GFD"]
THOST_FTDC_VC_AV = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_VC_AV"]
THOST_TERT_QUICK = _PLACEHOLDER_TRADER_SYMBOLS["THOST_TERT_QUICK"]
THOST_FTDC_AF_Delete = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_AF_Delete"]
THOST_FTDC_CC_Immediately = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_CC_Immediately"]
THOST_FTDC_D_Buy = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_D_Buy"]
THOST_FTDC_D_Sell = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_D_Sell"]
THOST_FTDC_FCC_NotForceClose = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_FCC_NotForceClose"]
THOST_FTDC_HF_Speculation = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_HF_Speculation"]
THOST_FTDC_OF_Close = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OF_Close"]
THOST_FTDC_OF_CloseToday = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OF_CloseToday"]
THOST_FTDC_OF_CloseYesterday = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OF_CloseYesterday"]
THOST_FTDC_OF_Open = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OF_Open"]
THOST_FTDC_OPT_LimitPrice = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OPT_LimitPrice"]
THOST_FTDC_AT_Execute = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_AT_Execute"]
THOST_FTDC_AT_Abandon = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_AT_Abandon"]
THOST_FTDC_OCF_CloseSelfOptionPosition = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OCF_CloseSelfOptionPosition"]
THOST_FTDC_OCF_ReserveOptionPosition = _PLACEHOLDER_TRADER_SYMBOLS["THOST_FTDC_OCF_ReserveOptionPosition"]

CThostFtdcInputExecOrderActionField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInputExecOrderActionField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcInputExecOrderField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInputExecOrderField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcInputOptionSelfCloseActionField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInputOptionSelfCloseActionField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcInputOptionSelfCloseField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInputOptionSelfCloseField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcInputOrderActionField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInputOrderActionField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcInputOrderField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInputOrderField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcInvestorPositionField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcInvestorPositionField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcQryInstrumentField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcQryInstrumentField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcQryInvestorPositionField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcQryInvestorPositionField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcQryOrderField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcQryOrderField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcQrySettlementInfoField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcQrySettlementInfoField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcQryTradeField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcQryTradeField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcQryTradingAccountField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcQryTradingAccountField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcReqAuthenticateField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcReqAuthenticateField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcReqUserLoginField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcReqUserLoginField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcSettlementInfoConfirmField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcSettlementInfoConfirmField", _PlaceholderStruct),
    _PlaceholderStruct,
)
CThostFtdcTraderApi = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcTraderApi", _PlaceholderTraderApi),
    _PlaceholderTraderApi,
)
CThostFtdcTraderSpi = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcTraderSpi", _PlaceholderTraderSpi),
    _PlaceholderTraderSpi,
)
CThostFtdcUserSystemInfoField = _LazySymbolProxy(
    lambda: _resolve_trader_symbol("CThostFtdcUserSystemInfoField", _PlaceholderStruct),
    _PlaceholderStruct,
)


__all__ = [
    "OPENCTP_AVAILABLE",
    "THOST_FTDC_AF_Delete",
    "THOST_FTDC_AT_Abandon",
    "THOST_FTDC_AT_Execute",
    "THOST_FTDC_CC_Immediately",
    "THOST_FTDC_D_Buy",
    "THOST_FTDC_D_Sell",
    "THOST_FTDC_FCC_NotForceClose",
    "THOST_FTDC_HF_Speculation",
    "THOST_FTDC_OCF_CloseSelfOptionPosition",
    "THOST_FTDC_OCF_ReserveOptionPosition",
    "THOST_FTDC_OF_Close",
    "THOST_FTDC_OF_CloseToday",
    "THOST_FTDC_OF_CloseYesterday",
    "THOST_FTDC_OF_Open",
    "THOST_FTDC_OPT_LimitPrice",
    "THOST_FTDC_TC_GFD",
    "THOST_FTDC_VC_AV",
    "THOST_TERT_QUICK",
    "CThostFtdcInputExecOrderActionField",
    "CThostFtdcInputExecOrderField",
    "CThostFtdcInputOptionSelfCloseActionField",
    "CThostFtdcInputOptionSelfCloseField",
    "CThostFtdcInputOrderActionField",
    "CThostFtdcInputOrderField",
    "CThostFtdcInvestorPositionField",
    "CThostFtdcMdApi",
    "CThostFtdcMdSpi",
    "CThostFtdcQryInstrumentField",
    "CThostFtdcQryInvestorPositionField",
    "CThostFtdcQryOrderField",
    "CThostFtdcQrySettlementInfoField",
    "CThostFtdcQryTradeField",
    "CThostFtdcQryTradingAccountField",
    "CThostFtdcReqAuthenticateField",
    "CThostFtdcReqUserLoginField",
    "CThostFtdcSettlementInfoConfirmField",
    "CThostFtdcTraderApi",
    "CThostFtdcTraderSpi",
    "CThostFtdcUserSystemInfoField",
    "create_md_spi_proxy",
    "create_trader_spi_proxy",
    "ensure_openctp_loaded",
    "mdapi",
]

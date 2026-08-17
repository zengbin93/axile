"""CTP 7x24 模拟环境联机烟雾测试.

本文件提供 CTP 两套 7x24 模拟环境的最小化联机校验：

- SimNow 7x24（上期技术官方）
- openctp TTS 7x24（第三方兼容平台）

每个用例只验证「能连上 → 能登录 → 能查询资金」这三件最小事，避免触发任何下单
或撤单逻辑，便于在 7x24 环境跑起来不污染账户。

⚠️ 默认全部跳过。凭据填在 ``tests/live.config.toml`` 的 ``[ctp_simnow_7x24]`` /
``[ctp_openctp_7x24]`` 段（见 ``tests/live.config.example.toml``；亦可用同名环境变量
``CTP_SIMNOW_7X24_INVESTOR_ID`` 等覆盖）。开启方式：

::

    # 仅跑 SimNow 7x24
    export RUN_LIVE_CTP_SIMNOW_7X24=1
    uv run pytest tests/live/test_ctp_7x24_smoke.py -v

    # 仅跑 openctp 7x24
    export RUN_LIVE_CTP_OPENCTP_7X24=1
    uv run pytest tests/live/test_ctp_7x24_smoke.py -v

详细配置说明见 ``tests/README.md``。
"""

from __future__ import annotations

import os
import socket
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

import pytest

from tests.live_env import config_value, require_live_config

_SIMNOW_DEFAULTS: dict[str, str] = {
    "TD_FRONT": "tcp://180.168.146.187:10130",
    "MD_FRONT": "tcp://180.168.146.187:10131",
    "BROKER_ID": "9999",
    "APP_ID": "simnow_client_test",
    "AUTH_CODE": "0000000000000000",
}

_OPENCTP_DEFAULTS: dict[str, str] = {
    "TD_FRONT": "tcp://trading.openctp.cn:30001",
    "MD_FRONT": "tcp://trading.openctp.cn:30011",
    "BROKER_ID": "9999",
    "APP_ID": "",
    "AUTH_CODE": "",
}


def _resolve_field(prefix: str, key: str, default: str | None) -> str:
    """读取一组 7x24 连接参数中的单个字段.

    解析优先级：环境变量（``PREFIX_KEY`` 全大写）> 配置文件 ``[prefix] key``（均小写）
    > ``default``。

    Parameters
    ----------
    prefix : str
        渠道前缀（如 ``"CTP_SIMNOW_7X24"``），小写后即配置文件 section 名。
    key : str
        字段名（如 ``"TD_FRONT"``），小写后即 section 内键名。
    default : str | None
        环境变量与文件均缺失时的兜底值；``None`` 视作空串。

    Returns
    -------
    str
        解析到的字段值。
    """
    return config_value(prefix.lower(), key.lower(), "" if default is None else default)


def _probe_tcp(address: str, timeout: float = 5.0) -> None:
    """对 ``tcp://host:port`` 形式的前置地址做一次 TCP 连通性探活.

    Parameters
    ----------
    address : str
        形如 ``tcp://host:port`` 的 CTP 前置地址。
    timeout : float, default=5.0
        单次连接的超时秒数。

    Raises
    ------
    pytest.skip.Exception
        当地址解析失败或端口不可达时直接 skip，避免在网络环境受限的机器上
        把测试判失败。
    """
    parsed = urlparse(address)
    if parsed.scheme != "tcp" or not parsed.hostname or not parsed.port:
        pytest.skip(f"前置地址格式不合法: {address!r}")

    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return
    except OSError as exc:  # 包含 timeout / refused / DNS 失败
        pytest.skip(f"无法连通 CTP 前置 {address}: {exc}")


def _build_ctp_config(prefix: str, defaults: dict[str, str]) -> dict[str, str]:
    """组装一组 CTP 7x24 连接参数，缺失字段使用 ``defaults`` 兜底."""
    return {
        "td_front": _resolve_field(prefix, "TD_FRONT", defaults["TD_FRONT"]),
        "md_front": _resolve_field(prefix, "MD_FRONT", defaults["MD_FRONT"]),
        "broker_id": _resolve_field(prefix, "BROKER_ID", defaults["BROKER_ID"]),
        "investor_id": _resolve_field(prefix, "INVESTOR_ID", None),
        "password": _resolve_field(prefix, "PASSWORD", None),
        "app_id": _resolve_field(prefix, "APP_ID", defaults["APP_ID"]),
        "auth_code": _resolve_field(prefix, "AUTH_CODE", defaults["AUTH_CODE"]),
    }


def _ensure_smoke_env(enable_flag: str, prefix: str) -> None:
    """统一守护：未开启开关或缺少 investor_id/password 时直接 skip."""
    require_live_config(enable_flag, prefix.lower(), ["investor_id", "password"])


def _run_smoke(config: dict[str, str]) -> None:
    """执行最小化联机烟雾流程（连接 → 登录 → 查账户 → 关闭）."""
    pytest.importorskip("openctp_ctp", reason="未安装 openctp_ctp，无法做联机烟雾测试")

    # 延迟导入：避免在仅做单元测试时也加载 native 扩展。
    from axile.executor.ctp.core.trader import CtpTrader

    _probe_tcp(config["td_front"])

    trader: Any = CtpTrader(
        host=config["td_front"],
        broker=config["broker_id"],
        user=config["investor_id"],
        password=config["password"],
        appid=config["app_id"],
        authcode=config["auth_code"],
        md_front=config["md_front"] or None,
    )

    try:
        trader.connect()
        trader.login()

        account = trader.query_account()
        assert account is not None, "query_account 返回空，疑似未登录或权限异常"
    finally:
        with suppress(Exception):
            trader.close()


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_CTP_SIMNOW_7X24", "0") != "1",
    reason="设置 RUN_LIVE_CTP_SIMNOW_7X24=1 后执行 SimNow 7x24 烟雾测试",
)
def test_simnow_7x24_smoke() -> None:
    """SimNow 7x24 模拟环境最小烟雾测试."""
    _ensure_smoke_env("RUN_LIVE_CTP_SIMNOW_7X24", "CTP_SIMNOW_7X24")
    config = _build_ctp_config("CTP_SIMNOW_7X24", _SIMNOW_DEFAULTS)
    _run_smoke(config)


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_CTP_OPENCTP_7X24", "0") != "1",
    reason="设置 RUN_LIVE_CTP_OPENCTP_7X24=1 后执行 openctp 7x24 烟雾测试",
)
def test_openctp_7x24_smoke() -> None:
    """openctp TTS 7x24 模拟环境最小烟雾测试."""
    _ensure_smoke_env("RUN_LIVE_CTP_OPENCTP_7X24", "CTP_OPENCTP_7X24")
    config = _build_ctp_config("CTP_OPENCTP_7X24", _OPENCTP_DEFAULTS)
    _run_smoke(config)

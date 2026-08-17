"""联机/手工测试的凭据统一入口.

Notes
-----
联机测试所需的交易所 / 柜台凭据统一从 tests 专用配置文件读取（默认
``tests/live.config.toml``，可用环境变量 ``AXILE_TEST_CONFIG`` 指向其他文件）；同名
环境变量（``SECTION_KEY`` 全大写）仍可覆盖文件值，便于 CI 或临时单次运行。
``RUN_LIVE_*`` 启用开关本身始终走环境变量。

该文件属于**测试基础设施，不是应用配置**：应用配置只在 ``config.toml``
（见 :mod:`axile.common.config`），量化数据源等应用级字段请直接从
:data:`axile.common.config.settings` 读，不要复制进本文件。
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

_TEST_CONFIG_ENV = "AXILE_TEST_CONFIG"
_DEFAULT_TEST_CONFIG = Path(__file__).resolve().parent / "live.config.toml"


@lru_cache(maxsize=8)
def _load_sections_at(path_str: str) -> dict[str, dict[str, Any]]:
    """加载指定 TOML 文件中的 ``[section]`` 表；文件缺失即返回空.

    Parameters
    ----------
    path_str : str
        配置文件路径（字符串形式，便于作为缓存键）。

    Returns
    -------
    dict[str, dict[str, Any]]
        section 名到其键值表的映射；顶层散键被忽略。
    """
    path = Path(path_str)
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def _load_sections() -> dict[str, dict[str, Any]]:
    """按当前 ``AXILE_TEST_CONFIG`` 指向加载测试配置 section 表."""
    path_str = os.environ.get(_TEST_CONFIG_ENV) or str(_DEFAULT_TEST_CONFIG)
    return _load_sections_at(path_str)


def _override_env_name(section: str, key: str) -> str:
    """由 section + key 推导可覆盖文件值的环境变量名（全大写）."""
    return f"{section}_{key}".upper()


def config_value(section: str, key: str, default: str = "") -> str:
    """读取一个联机测试配置项.

    解析优先级：同名环境变量（``SECTION_KEY`` 全大写）> 配置文件 ``[section] key``
    > ``default``。

    Parameters
    ----------
    section : str
        配置文件中的 section 名（如 ``"ctp"``）。
    key : str
        section 内的字段名（如 ``"api_key"``）。
    default : str, default=""
        环境变量与文件均缺失时返回的兜底值。

    Returns
    -------
    str
        解析到的字符串值。
    """
    env_value = os.getenv(_override_env_name(section, key))
    if env_value:
        return env_value
    file_value = _load_sections().get(section, {}).get(key)
    if file_value is not None and file_value != "":
        return str(file_value)
    return default


def require_live_config(enable_flag: str, section: str, keys: list[str]) -> dict[str, str]:
    """守护联机测试：校验启用开关与必填凭据后返回其值.

    Parameters
    ----------
    enable_flag : str
        形如 ``RUN_LIVE_*`` 的启用开关环境变量名；未置为 ``"1"`` 时 skip 当前用例。
    section : str
        tests 配置文件中的 section 名。
    keys : list[str]
        必填字段名列表；任一字段在环境变量与文件中均缺失即 skip。

    Returns
    -------
    dict[str, str]
        必填字段的 ``key -> value`` 映射。
    """
    if os.getenv(enable_flag, "0") != "1":
        pytest.skip(f"需要显式设置 {enable_flag}=1 后执行")

    resolved = {key: config_value(section, key) for key in keys}
    missing = [key for key, value in resolved.items() if not value]
    if missing:
        hint = ", ".join(f"[{section}] {key}" for key in missing)
        pytest.skip(f"缺少运行联机测试所需配置：{hint}（见 tests/live.config.example.toml）")
    return resolved

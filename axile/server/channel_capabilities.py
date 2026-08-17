"""根据渠道插件声明探测运行时依赖可用性."""

from __future__ import annotations

import importlib.util

from axile.channels import get_channel


def missing_packages(channel: str) -> list[str]:
    """
    返回渠道缺失的依赖包名列表.

    Parameters
    ----------
    channel : str
        待探测的交易渠道。

    Returns
    -------
    list[str]
        该渠道尚未安装的第三方包名；列表为空表示依赖齐备。
    """
    plugin = get_channel(channel)
    missing: list[str] = []
    for package in plugin.required_modules:
        try:
            found = importlib.util.find_spec(package) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            found = False
        if not found:
            missing.append(package)
    return missing


def install_extra(channel: str) -> str | None:
    """
    返回渠道对应的 pyproject extra 名.

    Parameters
    ----------
    channel : str
        待查询的交易渠道。

    Returns
    -------
    str | None
        可选依赖 extra 名；外部独立插件未使用公开包 extra 时返回 ``None``。
    """
    return get_channel(channel).install_extra

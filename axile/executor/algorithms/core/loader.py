"""算法加载器工具模块.

执行器使用注册机制（参见 `core.base`），通过导入算法包来填充注册表。
本模块负责加载位于 `axile.executor.algorithms.defaults` 下的内置算法。

同时提供辅助函数，用于加载用户提供的算法模块（插件），这些模块位于
`defaults/` 目录树之外。
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Iterable
from importlib import metadata

logger = logging.getLogger(__name__)


def load_default_algorithms() -> None:
    """导入 `axile.executor.algorithms.defaults` 下的所有算法包.

    导入包时会通过装饰器触发算法注册。
    """
    # 获取算法包名称（从当前包名中移除 '.core'）
    if __package__ is not None:
        algorithms_pkg_name = __package__.rsplit(".", 1)[0]
    else:
        # 回退方案：从 __name__ 中移除最后两个组件（例如 '.core.loader'）
        algorithms_pkg_name = __name__.rsplit(".", 2)[0]
    defaults_pkg_name = f"{algorithms_pkg_name}.defaults"
    defaults_pkg = importlib.import_module(defaults_pkg_name)

    modules = sorted(
        pkgutil.iter_modules(defaults_pkg.__path__, prefix=f"{defaults_pkg_name}."),
        key=lambda m: m.name,
    )

    for module in modules:
        leaf_name = module.name.rsplit(".", 1)[-1]
        if leaf_name.startswith("_"):
            continue
        importlib.import_module(module.name)


def load_algorithm_modules(modules: Iterable[str]) -> None:
    """导入用户提供的算法模块/包.

    每个导入的模块应在导入时通过 `@register_algorithm(...)` 注册一个或多个算法。

    示例:
        load_algorithm_modules(["my_project.axile_algorithms"])
    """
    for module in modules:
        module = module.strip()
        if not module:
            continue
        importlib.import_module(module)


def load_entrypoint_algorithms(group: str = "axile.algorithms", *, strict: bool = False) -> None:
    """从 Python 打包入口点加载算法.

    插件可以在其 `pyproject.toml` 中声明入口点：

        [project.entry-points."axile.algorithms"]
        my_plugin = "my_plugin.axile_algorithms"

    入口点目标可以是：
    - 模块（导入时会触发注册），或
    - 可调用对象（加载后会被调用一次）。
    """
    eps = metadata.entry_points()
    selected = eps.select(group=group)

    for ep in selected:
        try:
            loaded = ep.load()
            if callable(loaded):
                loaded()
        except Exception:
            if strict:
                raise
            logger.exception(
                "加载算法入口点失败 %s=%s",
                getattr(ep, "name", "<unknown>"),
                getattr(ep, "value", "<unknown>"),
            )

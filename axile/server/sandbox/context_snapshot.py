"""
自定义组合脚本的上下文快照.

用户脚本拿到的 ``context`` 在主进程里是 :class:`axile.server.context.Context`，
它持有数据库会话，**无法跨进程传递**。本模块把它拍扁成一组纯标量，用于送进
沙箱子进程；子进程侧再包装成一个鸭子类型对象，对脚本而言属性访问行为不变。

Notes
-----
该模块**刻意不 import 任何 server 侧模块**：子进程以 ``spawn`` 启动，会重新
import 目标模块，若这里牵出 ``axile.server.context`` 就会连带拉起 fastapi /
sqlmodel / api.deps，既拖慢启动又把不必要的依赖带进沙箱。
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "CONTEXT_SCALAR_PROPERTIES",
    "ContextSnapshot",
    "SnapshotContext",
    "snapshot_context",
]

CONTEXT_SCALAR_PROPERTIES: tuple[str, ...] = (
    # account_id 是 ``Context`` 的实例属性（非 property），脚本可以合法读取它；
    # 只按类上的 property 枚举会漏掉，务必保留。
    "account_id",
    "today_return",
    "today_max_drawdown",
    "current_leverage",
    "long_market_value",
    "short_market_value",
    "net_market_value",
    "yesterday_total_balance",
    "available_balance",
    "frozen_funds",
    "total_balance",
    "used_margin",
    "margin_usage_ratio",
    "consecutive_loss_days",
    "last_update_time",
)
"""``Context`` 对用户脚本暴露的标量属性名。

与 :class:`axile.server.context.SampleContext` 的字段集合保持一致；两者任一侧
新增字段时，这里必须同步（``tests`` 中有断言守住该一致性）。
"""


@dataclass(slots=True)
class ContextSnapshot:
    """
    可跨进程传递的账户上下文快照.

    Attributes
    ----------
    values : dict[str, object]
        成功取值的标量属性。
    errors : dict[str, str]
        取值时抛错的属性名到错误描述的映射；子进程在脚本**访问该属性时**才
        重新抛出，以保持与主进程内懒加载一致的语义。
    has_data : bool
        ``Context.has_data()`` 的取值。
    execution_count : int
        ``Context.get_execution_count()`` 的取值。
    """

    values: dict[str, object] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    has_data: bool = False
    execution_count: int = 0


class SnapshotContext:
    """
    子进程侧的上下文对象，对脚本呈现与 ``Context`` 一致的属性.

    Notes
    -----
    取值失败的属性在**访问时**才抛 ``RuntimeError``，而不是在快照阶段就让整个
    脚本失败——主进程里这些属性是懒加载的，只有真正读到才会触发查询与报错，
    这里保持同样的语义，避免「脚本明明没用到某属性，却因它取值失败而跑不起来」。
    """

    def __init__(self, snapshot: ContextSnapshot) -> None:
        """
        由快照构造子进程侧上下文.

        Parameters
        ----------
        snapshot : ContextSnapshot
            主进程采集的上下文快照。
        """
        self._values = dict(snapshot.values)
        self._errors = dict(snapshot.errors)
        self._has_data = snapshot.has_data
        self._execution_count = snapshot.execution_count

    def __getattr__(self, name: str) -> object:
        """
        按快照返回标量属性，取值失败的属性在此重新抛错.

        Parameters
        ----------
        name : str
            属性名。

        Returns
        -------
        object
            快照中记录的属性值。

        Raises
        ------
        RuntimeError
            该属性在主进程取值时即失败。
        AttributeError
            快照中不存在该属性。
        """
        if name in self._values:
            return self._values[name]
        if name in self._errors:
            raise RuntimeError(f"账户上下文属性 {name} 取值失败: {self._errors[name]}")
        raise AttributeError(name)

    def has_data(self) -> bool:
        """
        返回账户是否有可用的执行记录数据.

        Returns
        -------
        bool
            与主进程 ``Context.has_data()`` 一致的取值。
        """
        return self._has_data

    def get_execution_count(self) -> int:
        """
        返回当日执行次数.

        Returns
        -------
        int
            与主进程 ``Context.get_execution_count()`` 一致的取值。
        """
        return self._execution_count


def snapshot_context(context: object | None) -> ContextSnapshot | None:
    """
    把账户上下文对象拍扁为可跨进程传递的快照.

    Parameters
    ----------
    context : object | None
        主进程侧的 ``Context`` 或 ``SampleContext``；``None`` 表示脚本不需要上下文。

    Returns
    -------
    ContextSnapshot | None
        对应快照；``context`` 为 ``None`` 时返回 ``None``。

    Notes
    -----
    逐属性 ``try/except`` 而非整体取值：``Context`` 的属性各自触发独立查询，
    任一属性失败不应牵连其余属性（对应失败在子进程访问时才抛出）。
    ``SampleContext`` 没有 ``has_data`` / ``get_execution_count``，缺失时按
    「有数据、0 次执行」处理，与 dry-run 的既有行为一致。
    """
    if context is None:
        return None

    snapshot = ContextSnapshot()
    for name in CONTEXT_SCALAR_PROPERTIES:
        try:
            snapshot.values[name] = getattr(context, name)
        except Exception as exc:  # noqa: BLE001 - 单个属性失败不应牵连其余属性
            snapshot.errors[name] = f"{type(exc).__name__}: {exc}"

    snapshot.has_data = _safe_call(context, "has_data", default=True)
    snapshot.execution_count = _safe_call(context, "get_execution_count", default=0)
    return snapshot


def _safe_call(context: object, name: str, *, default: object) -> object:
    """
    调用上下文的无参方法，缺失或抛错时回退到默认值.

    Parameters
    ----------
    context : object
        上下文对象。
    name : str
        方法名。
    default : object
        方法缺失或调用失败时的回退值。

    Returns
    -------
    object
        方法返回值或回退值。
    """
    method = getattr(context, name, None)
    if not callable(method):
        return default
    try:
        return method()
    except Exception:  # noqa: BLE001 - 上下文辅助方法失败不应阻断脚本执行
        return default

"""`AbstractExecutor` 的 execution runtime 宿主与基础访问 facade."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from loguru import logger

from axile.common.trade_channel import TradeChannel
from axile.executor.algorithms.utils import clock_now
from axile.executor.china_futures_session import is_regular_night_session_transition
from axile.executor.execution_query_runtime import ExecutionQueryRuntime, ExecutionQueryRuntimeBridge
from axile.executor.execution_runtime import ExecutionRuntime, ExecutionRuntimeBindings
from axile.executor.models.unified_input import AccountConfig, UnifiedStandardInput

if TYPE_CHECKING:
    from axile.executor.abstract_executor.base import AbstractExecutor
    from axile.executor.trading_calendar import TradingCalendar


def _executor(owner: object) -> AbstractExecutor:
    """将 mixin 宿主收窄为 `AbstractExecutor`."""
    return cast("AbstractExecutor", owner)


class AbstractExecutorExecutionRuntimeHostMixin:
    """
    承载 execution runtime 宿主、binding 与查询运行时访问逻辑。

    Notes
    -----
    该 mixin 只负责 runtime 宿主初始化、binding 同步，以及
    execution runtime / query runtime 的基础访问入口。
    """

    def __init__(self, channel_type: TradeChannel, account_config: AccountConfig | None = None) -> None:
        """
        初始化执行器宿主与 runtime 容器。

        Parameters
        ----------
        channel_type : TradeChannel
            当前执行器所属的交易渠道类型。
        account_config : AccountConfig | None, default=None
            账户配置对象；提供时会在初始化阶段建立连接。
        """
        executor = _executor(self)
        executor.channel_type = channel_type
        executor.logger = logger
        executor.account_config = account_config
        executor._runtime_bindings = ExecutionRuntimeBindings()
        executor._active_execution_runtime = None
        executor._execution_query_runtime_bridge = ExecutionQueryRuntimeBridge(executor)
        executor._trading_calendar = None
        executor._channel_calendar_id = None
        executor._channel_calendar_fallback_id = None

        if account_config is not None:
            executor._initialize_connection(account_config)

    def set_trading_calendar(self, calendar: TradingCalendar | None) -> None:
        """绑定执行器使用的本地交易日历读取器。"""
        _executor(self)._trading_calendar = calendar

    def set_channel_calendar(self, calendar_id: str | None, fallback_calendar_id: str | None = None) -> None:
        """绑定当前渠道由插件声明的主日历及可选存量回退。"""
        executor = _executor(self)
        executor._channel_calendar_id = calendar_id
        executor._channel_calendar_fallback_id = fallback_calendar_id

    def _is_channel_calendar_open(self, day: date | None = None) -> bool:
        """查询当前渠道声明的日历；主日历未覆盖时才读取存量回退。"""
        executor = _executor(self)
        calendar_id = cast("str | None", getattr(executor, "_channel_calendar_id", None))
        if calendar_id is None:
            return True
        current = day or date.today()
        calendar = cast("TradingCalendar | None", getattr(executor, "_trading_calendar", None))
        if calendar is not None:
            try:
                is_open = calendar.is_open(calendar_id, current)
                if is_open is not None:
                    return is_open
                fallback_id = cast("str | None", getattr(executor, "_channel_calendar_fallback_id", None))
                if fallback_id is not None:
                    fallback_open = calendar.is_open(fallback_id, current)
                    if fallback_open is not None:
                        return fallback_open
                executor.logger.warning("{} {} 缺少有效交易日历，继续放行", calendar_id, current)
            except Exception as exc:  # noqa: BLE001 - 日历故障按兼容口径降级
                executor.logger.warning("读取 {} {} 交易日历失败，继续放行: {}", calendar_id, current, exc)
        else:
            executor.logger.warning("未绑定本地交易日历，{} {} 继续放行", calendar_id, current)
        return True

    def _is_calendar_open(self, calendar_id: str, day: date | None = None) -> bool:
        """查询交易日历；未配置、缺失或读取失败时按原排程执行。"""
        executor = _executor(self)
        current = day or date.today()
        calendar = cast("TradingCalendar | None", getattr(executor, "_trading_calendar", None))
        if calendar is not None:
            try:
                is_open = calendar.is_open(calendar_id, current)
                if is_open is not None:
                    return is_open
                executor.logger.warning("{} {} 缺少有效交易日历，继续放行", calendar_id, current)
            except Exception as exc:  # noqa: BLE001 - 日历故障按兼容口径降级
                executor.logger.warning("读取 {} {} 交易日历失败，继续放行: {}", calendar_id, current, exc)
        else:
            executor.logger.warning("未绑定本地交易日历，{} {} 继续放行", calendar_id, current)
        return True

    def _is_china_futures_session_open(self, now: datetime | None = None) -> bool:
        """按上海自然时间和现有交易日历判断中国期货日夜盘。

        00:00 至 02:30 仍属于前一自然日开始的夜盘。夜盘仅允许普通相邻
        交易日，或周五至下周一的标准周末转换；节假日前不放行。这里只修正
        日历归属，具体品种更窄的收盘时间仍由交易渠道校验。
        """
        current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        current_time = current.timetz().replace(tzinfo=None)
        if current_time >= time(21):
            session_start_day = current.date()
        elif current_time <= time(2, 30):
            session_start_day = current.date() - timedelta(days=1)
        else:
            return self._is_channel_calendar_open(current.date())

        executor = _executor(self)
        calendar_id = cast("str | None", getattr(executor, "_channel_calendar_id", None))
        calendar = cast("TradingCalendar | None", getattr(executor, "_trading_calendar", None))
        if calendar_id is None or calendar is None:
            return self._is_channel_calendar_open(session_start_day)

        try:
            session_state = calendar.is_open(calendar_id, session_start_day)
            if session_state is None:
                executor.logger.warning("{} {} 缺少有效交易日历，继续放行", calendar_id, session_start_day)
                return True
            if not session_state:
                return False
            for offset in range(1, 15):
                candidate = session_start_day + timedelta(days=offset)
                state = calendar.is_open(calendar_id, candidate)
                if state is None:
                    executor.logger.warning("{} {} 缺少有效交易日历，继续放行", calendar_id, candidate)
                    return True
                if state:
                    return is_regular_night_session_transition(session_start_day, candidate)
        except Exception as exc:  # noqa: BLE001 - 日历故障沿用现有兼容口径
            executor.logger.warning("读取中国期货夜盘日历失败，继续放行: {}", exc)
            return True
        return False

    def _reset_execution_state(self, standard_input: UnifiedStandardInput) -> None:
        """
        在每次新的执行开始前重置 active runtime。

        Parameters
        ----------
        standard_input : UnifiedStandardInput
            本次执行的统一输入；总超时额度从中解析。
        """
        executor = _executor(self)
        runtime = executor.prepare_execution_runtime()
        runtime.reset_for_execute(execution_timeout=executor._resolve_execution_deadline_seconds(standard_input))

    def _resolve_execution_deadline_seconds(self, standard_input: UnifiedStandardInput) -> int:
        """
        解析本次执行的总超时秒数。

        Parameters
        ----------
        standard_input : UnifiedStandardInput
            本次执行的统一输入。

        Returns
        -------
        int
            总超时秒数；``<= 0`` 表示本次执行不启用 deadline。

        Notes
        -----
        单独抽成钩子是为了让不按真实墙钟走的执行器（如仿真执行器，其时钟会在等待时
        直接推进仿真时间）能整体关闭 deadline，而不必要求每个调用方都记得传 ``0``。
        """
        return standard_input.execution_timeout

    def _ensure_runtime_host(self) -> None:
        """为绕过 `__init__` 的轻量实例补齐 runtime 宿主字段。"""
        executor = _executor(self)
        # 测试和某些轻量构造路径会绕过标准初始化，这里只补最小运行时骨架。
        if "_runtime_bindings" not in executor.__dict__:
            executor._runtime_bindings = ExecutionRuntimeBindings()
        if "_active_execution_runtime" not in executor.__dict__:
            executor._active_execution_runtime = None
        if "_execution_query_runtime_bridge" not in executor.__dict__:
            executor._execution_query_runtime_bridge = ExecutionQueryRuntimeBridge(executor)

    def _ensure_connection(self) -> None:
        """确保连接有效，连接断开时抛出异常。"""
        executor = _executor(self)
        if not executor._verify_connection():
            raise ConnectionError(f"{executor.channel_type.value} 连接无效，请检查网络和账户配置")

    def _sync_active_runtime_bindings(self) -> None:
        """将宿主上的 binding 变更同步到当前 active runtime。"""
        executor = _executor(self)
        runtime = executor.get_active_execution_runtime()
        if runtime is not None:
            runtime.sync_bindings()

    def _update_runtime_binding(self, field_name: str, value: object) -> None:
        """
        更新宿主上的单个 runtime binding 并同步到 active runtime。

        Parameters
        ----------
        field_name : str
            需要写入 `ExecutionRuntimeBindings` 的字段名。
        value : object
            需要写入 binding 的字段值。
        """
        executor = _executor(self)
        executor._ensure_runtime_host()
        setattr(executor._runtime_bindings, field_name, value)
        executor._sync_active_runtime_bindings()

    def get_active_execution_runtime(self) -> ExecutionRuntime | None:
        """
        仅读取当前 active execution runtime，不触发创建。

        Returns
        -------
        ExecutionRuntime | None
            当前活跃执行运行时；若尚未创建则返回 ``None``。
        """
        executor = _executor(self)
        executor._ensure_runtime_host()
        return cast("ExecutionRuntime | None", getattr(executor, "_active_execution_runtime", None))

    def require_execution_runtime(self) -> ExecutionRuntime:
        """
        获取当前 execution runtime；不存在时显式创建。

        Returns
        -------
        ExecutionRuntime
            当前执行应使用的运行时对象。
        """
        executor = _executor(self)
        executor._ensure_runtime_host()
        runtime = executor.get_active_execution_runtime()
        if runtime is None:
            # binding 先挂在宿主上，真正需要 runtime 时再实例化，避免只读路径平白制造状态。
            runtime = ExecutionRuntime(owner=executor, bindings=executor._runtime_bindings)
            executor._active_execution_runtime = runtime
        else:
            runtime.sync_bindings()
        return runtime

    @property
    def start_time(self) -> datetime | None:
        """
        返回当前 execution runtime 的开始时间。

        Returns
        -------
        datetime | None
            当前活跃执行运行时的开始时间；若尚未创建则返回 ``None``。
        """
        executor = _executor(self)
        runtime = executor.get_active_execution_runtime()
        if runtime is not None:
            return runtime.start_time
        return None

    @start_time.setter
    def start_time(self, value: datetime | None) -> None:
        runtime = _executor(self).require_execution_runtime()
        runtime.start_time = value or clock_now()

    def prepare_execution_runtime(self) -> ExecutionRuntime:
        """
        创建或复用当前 execution runtime。

        Returns
        -------
        ExecutionRuntime
            当前执行应使用的运行时对象。
        """
        return _executor(self).require_execution_runtime()

    def clear_execution_runtime(self) -> None:
        """清空当前 active execution runtime。"""
        executor = _executor(self)
        executor._ensure_runtime_host()
        executor._active_execution_runtime = None

    def get_active_execution_query_runtime(self) -> ExecutionQueryRuntime | None:
        """
        返回当前 active runtime 持有的 execution 查询运行时。

        Returns
        -------
        ExecutionQueryRuntime | None
            当前活跃运行时持有的查询运行时；不存在时返回 ``None``。
        """
        executor = _executor(self)
        runtime = executor.get_active_execution_runtime()
        if runtime is not None:
            return runtime.get_execution_query_runtime()
        return None

    def set_active_execution_query_runtime(self, runtime: ExecutionQueryRuntime) -> None:
        """
        覆盖当前 active runtime 的 execution 查询运行时。

        Parameters
        ----------
        runtime : ExecutionQueryRuntime
            需要绑定到当前活跃运行时的查询运行时对象。
        """
        # query runtime 总是附着在 active runtime 上，不单独缓存到宿主 binding。
        active_runtime = _executor(self).require_execution_runtime()
        active_runtime._execution_query_runtime = runtime

    def get_execution_query_runtime_bridge(self) -> ExecutionQueryRuntimeBridge:
        """
        返回 execution 查询 runtime 的桥接器。

        Returns
        -------
        ExecutionQueryRuntimeBridge
            当前执行器持有的查询运行时桥接器。
        """
        executor = _executor(self)
        executor._ensure_runtime_host()
        return executor._execution_query_runtime_bridge

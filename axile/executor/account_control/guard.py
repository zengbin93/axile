"""
提供账户控制在执行期的内存态防护逻辑.

Notes
-----
该模块负责在单次 execution 内评估额度、执行等待或阻断动作，并产出待刷盘的
计数器增量与事件事实。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import Callable
from zoneinfo import ZoneInfo

from axile.common.trade_channel import TradeChannel
from axile.executor.account_control.exceptions import AccountControlBlockedError
from axile.executor.account_control.models import (
    AccountControlBucketType,
    AccountControlCounterDeltaWrite,
    AccountControlDecision,
    AccountControlEventWrite,
    AccountControlOperationPolicy,
    AccountControlPolicy,
    AccountControlScopePolicy,
    AccountControlScopeType,
    AccountControlTriggerBehavior,
)
from axile.executor.account_control.registry import ensure_default_account_control_registry_bootstrapped
from axile.executor.account_control.snapshot import (
    AccountControlCounterSnapshot,
    AccountControlRecentAllowedSnapshot,
)
from axile.executor.algorithms.utils.clock import Clock, clock_now, get_default_clock

type AccountCounterKey = tuple[str, AccountControlBucketType, str, str]
type SymbolCounterKey = tuple[str, str, AccountControlBucketType, str, str]
type RecentAccountKey = tuple[str]
type RecentSymbolKey = tuple[str, str]
type GroupCounterKey = tuple[str, AccountControlBucketType, str, str]
type GroupRecentKey = tuple[str]


def _normalize_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    if metadata is None:
        return {}
    return {str(key): value for key, value in metadata.items()}


def _merge_metadata(
    base: Mapping[str, object] | None,
    overlay: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        **_normalize_metadata(base),
        **_normalize_metadata(overlay),
    }


@dataclass(frozen=True)
class AccountControlWindow:
    """
    表示当前时刻对应的控制时间窗口.

    Attributes
    ----------
    control_date : str
        当前控制日期。
    day_bucket_start : str
        日级时间桶起始时间。
    minute_bucket_start : str
        分钟级时间桶起始时间。
    """

    control_date: str
    day_bucket_start: str
    minute_bucket_start: str


@dataclass(frozen=True)
class AccountControlEvaluationContext:
    """
    表示一次额度评估使用的时间上下文.

    Attributes
    ----------
    local_now : datetime
        当前策略时区下的本地时间。
    occurred_at_ms : int
        当前评估对应的毫秒时间戳。
    window : AccountControlWindow
        当前时间所属的控制窗口。
    """

    local_now: datetime
    occurred_at_ms: int
    window: AccountControlWindow


@dataclass(frozen=True)
class AccountControlEnforcementDecision:
    """
    表示额度评估后的执行动作.

    Attributes
    ----------
    kind : str
        动作类型，可能为 ``allow``、``wait`` 或 ``block``。
    wait_ms : int
        当需要等待时的等待毫秒数。
    message : str | None
        阻断时使用的错误消息。
    outcome : str | None
        阻断事件记录的 outcome。
    """

    kind: str
    wait_ms: int = 0
    message: str | None = None
    outcome: str | None = None

    @classmethod
    def allow(cls) -> "AccountControlEnforcementDecision":
        """
        构造允许继续执行的决策.

        Returns
        -------
        AccountControlEnforcementDecision
            ``kind`` 为 ``allow`` 的决策对象。
        """
        return cls(kind="allow")

    @classmethod
    def wait(cls, wait_ms: int) -> "AccountControlEnforcementDecision":
        """
        构造需要等待的决策.

        Parameters
        ----------
        wait_ms : int
            建议等待的毫秒数。

        Returns
        -------
        AccountControlEnforcementDecision
            ``kind`` 为 ``wait`` 的决策对象。
        """
        return cls(kind="wait", wait_ms=max(wait_ms, 0))

    @classmethod
    def block(cls, message: str, outcome: str) -> "AccountControlEnforcementDecision":
        """
        构造直接阻断的决策.

        Parameters
        ----------
        message : str
            阻断时使用的错误消息。
        outcome : str
            阻断事件记录的 outcome。

        Returns
        -------
        AccountControlEnforcementDecision
            ``kind`` 为 ``block`` 的决策对象。
        """
        return cls(kind="block", message=message, outcome=outcome)


@dataclass(frozen=True)
class AccountControlResolvedAttempt:
    """
    表示一次账户控制尝试在等待收敛后的最终结果.

    Attributes
    ----------
    context : AccountControlEvaluationContext
        最终放行或阻断时对应的时间上下文。
    decision : AccountControlEnforcementDecision
        最终执行动作。
    """

    context: AccountControlEvaluationContext
    decision: AccountControlEnforcementDecision


def resolve_control_window(
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> AccountControlWindow:
    """
    按策略时区解析当前的日级与分钟级时间桶.

    Parameters
    ----------
    timezone_name : str
        需要使用的 IANA 时区名称。
    now : datetime | None, optional
        指定的当前时间；为空时使用系统当前时间。

    Returns
    -------
    AccountControlWindow
        当前时间对应的控制窗口。
    """
    tz = ZoneInfo(timezone_name)
    current = clock_now(tz=tz) if now is None else now
    local_now = current.replace(tzinfo=tz) if current.tzinfo is None else current.astimezone(tz)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    minute_start = local_now.replace(second=0, microsecond=0, tzinfo=None)
    return AccountControlWindow(
        control_date=local_now.date().isoformat(),
        day_bucket_start=day_start.isoformat(),
        minute_bucket_start=minute_start.isoformat(),
    )


def _copy_scope_policy(scope_policy: AccountControlScopePolicy | None) -> AccountControlScopePolicy | None:
    if scope_policy is None:
        return None
    return AccountControlScopePolicy.model_validate(scope_policy.model_dump(mode="json"))


def _merge_scope_policies(
    base_scope: AccountControlScopePolicy | None,
    override_scope: AccountControlScopePolicy | None,
) -> AccountControlScopePolicy | None:
    if base_scope is None and override_scope is None:
        return None
    if base_scope is None:
        return _copy_scope_policy(override_scope)
    if override_scope is None:
        return _copy_scope_policy(base_scope)
    return AccountControlScopePolicy(
        per_minute=base_scope.per_minute if override_scope.per_minute is None else override_scope.per_minute,
        per_day=base_scope.per_day if override_scope.per_day is None else override_scope.per_day,
        min_interval_ms=base_scope.min_interval_ms
        if override_scope.min_interval_ms is None
        else override_scope.min_interval_ms,
    )


class AccountControlAttempt:
    """
    表示一次已经放行的账户控制尝试.

    Notes
    -----
    该对象用于在真实对外交互完成后回填最终 outcome 与附加元数据。
    """

    def __init__(self, guard: "AccountControlGuard | None", event_index: int | None) -> None:
        self._guard = guard
        self._event_index = event_index

    def record_outcome(self, outcome: str, *, metadata: Mapping[str, object] | None = None) -> None:
        """
        在对外交互结果落定后更新事件事实.

        Parameters
        ----------
        outcome : str
            调用完成后的最终结果。
        metadata : Mapping[str, object] | None, optional
            需要合并回事件中的附加元数据。
        """
        if self._guard is None or self._event_index is None:
            return
        self._guard.update_event_outcome(self._event_index, outcome=outcome, metadata=metadata)


class AccountControlGuard:
    """
    管理单次 execution 期间账户控制状态的守卫对象.

    Attributes
    ----------
    account_id : int | None
        当前执行关联的账户 ID。
    execution_id : str | None
        当前执行会话 ID。
    channel : TradeChannel
        当前交易渠道。
    policy : AccountControlPolicy | None
        当前生效的账户控制策略；为空时表示不启用控制。
    baseline : AccountControlCounterSnapshot
        从持久化层读取的基线计数快照。

    Notes
    -----
    阅读主线建议：

    1. 从 `begin_operation()` 进入一次额度检查。
    2. 再看 `_resolve_operation_attempt()` 如何在单轮评估中产生 allow / wait / block 决策。
    3. 最后看 `flush_records()` 如何导出本次 execution 累积的事件与计数器增量。
    """

    def __init__(
        self,
        *,
        account_id: int | None,
        execution_id: str | None,
        channel: TradeChannel,
        policy: AccountControlPolicy | None,
        baseline: AccountControlCounterSnapshot,
        recent_allowed_snapshot: AccountControlRecentAllowedSnapshot | None = None,
        clock: Callable[[], datetime] | None = None,
        wait_clock: Clock | None = None,
        sleep: Callable[[float], None] | None = None,
        wait_poll_interval_ms: int = 100,
        termination_checkpoint: Callable[[str | None], None] | None = None,
    ) -> None:
        self.account_id = account_id
        self.execution_id = execution_id
        self.channel = channel
        self.policy = policy
        self.baseline = baseline
        self._clock = clock
        self._wait_clock = get_default_clock() if wait_clock is None else wait_clock
        self._sleep = self._wait_clock.sleep if sleep is None else sleep
        self._wait_poll_interval_ms = max(wait_poll_interval_ms, 1)
        self._termination_checkpoint = termination_checkpoint
        self._state_lock = RLock()
        self._event_seq = 0
        self._events: list[AccountControlEventWrite] = []
        self._account_counters: dict[AccountCounterKey, int] = {}
        self._symbol_counters: dict[SymbolCounterKey, int] = {}
        self._group_counters: dict[GroupCounterKey, int] = {}
        snapshot = AccountControlRecentAllowedSnapshot() if recent_allowed_snapshot is None else recent_allowed_snapshot
        self._recent_account_allowed_at: dict[RecentAccountKey, int] = dict(snapshot.account_timestamps)
        self._recent_symbol_allowed_at: dict[RecentSymbolKey, int] = dict(snapshot.symbol_timestamps)
        self._recent_group_allowed_at: dict[GroupRecentKey, int] = {}
        self._baseline_control_date = None if policy is None else self._current_context().window.control_date
        self._registry = ensure_default_account_control_registry_bootstrapped()

    def set_termination_checkpoint(self, callback: Callable[[str | None], None] | None) -> None:
        """
        绑定等待期间可调用的终止检查点.

        Parameters
        ----------
        callback : Callable[[str | None], None] | None
            等待轮询期间反复调用的检查函数；参数为当前 symbol。
        """
        self._termination_checkpoint = callback

    def begin_operation(
        self,
        operation: str,
        *,
        symbol: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AccountControlAttempt:
        """
        在真实对外交互前评估额度并记录一次尝试.

        Parameters
        ----------
        operation : str
            当前调用对应的操作键。
        symbol : str | None, optional
            本次调用关联的交易标的代码。
        metadata : Mapping[str, object] | None, optional
            需要随事件记录的附加元数据。

        Returns
        -------
        AccountControlAttempt
            已放行时返回的尝试对象；若控制未启用则返回空尝试对象。

        Raises
        ------
        AccountControlBlockedError
            当额度规则要求阻断时抛出。
        """
        if not self._enabled():
            return AccountControlAttempt(None, None)
        assert self.account_id is not None
        assert self.execution_id is not None

        while True:
            # 同一把锁覆盖“检查额度 → 预占额度 → 记录事件”，避免并发 symbol
            # 同时看到旧快照后全部放行。等待必须在锁外进行，否则一个受限请求会
            # 阻塞其他本可立即执行的 operation，也会拖慢终止检查。
            with self._state_lock:
                resolved_attempt = self._resolve_operation_attempt(
                    operation=operation,
                    symbol=symbol,
                )
                if resolved_attempt.decision.kind == "block":
                    self._record_blocked_attempt(
                        operation=operation,
                        symbol=symbol,
                        metadata=metadata,
                        resolved_attempt=resolved_attempt,
                    )
                if resolved_attempt.decision.kind == "allow":
                    return self._record_allowed_attempt(
                        operation=operation,
                        symbol=symbol,
                        metadata=metadata,
                        resolved_attempt=resolved_attempt,
                    )

                wait_ms = resolved_attempt.decision.wait_ms
            self._wait_for_quota(wait_ms, symbol)

    def update_event_outcome(
        self,
        event_index: int,
        *,
        outcome: str,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """
        更新某次已记录事件的最终结果.

        Parameters
        ----------
        event_index : int
            需要更新的事件索引。
        outcome : str
            事件最终结果。
        metadata : Mapping[str, object] | None, optional
            需要合并到原事件中的附加元数据。
        """
        with self._state_lock:
            event = self._events[event_index]
            self._events[event_index] = event.model_copy(
                update={
                    "outcome": outcome,
                    "metadata": _merge_metadata(event.metadata, metadata),
                }
            )

    def flush_records(self) -> tuple[list[AccountControlCounterDeltaWrite], list[AccountControlEventWrite]]:
        """
        导出当前 execution 产生的计数增量与事件事实.

        Returns
        -------
        tuple[list[AccountControlCounterDeltaWrite], list[AccountControlEventWrite]]
            待刷盘的计数器增量列表与事件列表。
        """
        if not self._enabled():
            return [], []
        assert self.account_id is not None
        assert self.execution_id is not None

        with self._state_lock:
            counter_deltas = self._build_counter_deltas()
            return counter_deltas, list(self._events)

    def _enabled(self) -> bool:
        return self.account_id is not None and self.execution_id is not None and self.policy is not None

    def _current_context(self) -> AccountControlEvaluationContext:
        assert self.policy is not None
        tz = ZoneInfo(self.policy.timezone)
        if self._clock is None:
            localized = datetime.fromtimestamp(self._wait_clock.time(), tz)
        else:
            current = self._clock()
            localized = current.replace(tzinfo=tz) if current.tzinfo is None else current.astimezone(tz)
        return AccountControlEvaluationContext(
            local_now=localized,
            occurred_at_ms=int(localized.timestamp() * 1000),
            window=resolve_control_window(self.policy.timezone, now=localized),
        )

    def _next_event_seq(self) -> int:
        self._event_seq += 1
        return self._event_seq

    def _build_event_uid(
        self,
        seq: int,
        operation: str,
        symbol: str | None,
        decision: AccountControlDecision,
    ) -> str:
        return f"{self.execution_id}:{seq}:{operation}:{symbol or '-'}:{decision.value}"

    def _resolve_operation_attempt(
        self,
        *,
        operation: str,
        symbol: str | None,
    ) -> AccountControlResolvedAttempt:
        """返回当前时刻的一轮额度评估结果，不在此处执行等待。"""
        context = self._current_context()
        decision = self._evaluate_enforcement(
            operation=operation,
            symbol=symbol,
            context=context,
        )
        return AccountControlResolvedAttempt(context=context, decision=decision)

    def _record_blocked_attempt(
        self,
        *,
        operation: str,
        symbol: str | None,
        metadata: Mapping[str, object] | None,
        resolved_attempt: AccountControlResolvedAttempt,
    ) -> None:
        decision = resolved_attempt.decision
        assert decision.kind == "block"
        assert decision.message is not None
        assert decision.outcome is not None

        self._append_operation_event(
            operation=operation,
            symbol=symbol,
            metadata=metadata,
            control_date=resolved_attempt.context.window.control_date,
            decision=AccountControlDecision.BLOCKED,
            counted=False,
            outcome=decision.outcome,
            occurred_at_ms=resolved_attempt.context.occurred_at_ms,
        )
        raise AccountControlBlockedError(
            decision.message,
            account_id=self.account_id,
            execution_id=self.execution_id,
            channel=self.channel,
            operation=operation,
            symbol=symbol,
        )

    def _record_allowed_attempt(
        self,
        *,
        operation: str,
        symbol: str | None,
        metadata: Mapping[str, object] | None,
        resolved_attempt: AccountControlResolvedAttempt,
    ) -> AccountControlAttempt:
        track_symbol_scope = self._should_track_symbol_scope(operation=operation, symbol=symbol)
        self._apply_allowed_side_effects(
            operation=operation,
            symbol=symbol,
            window=resolved_attempt.context.window,
            occurred_at_ms=resolved_attempt.context.occurred_at_ms,
            track_symbol_scope=track_symbol_scope,
        )
        event_index = self._append_operation_event(
            operation=operation,
            symbol=symbol,
            metadata=metadata,
            control_date=resolved_attempt.context.window.control_date,
            decision=AccountControlDecision.ALLOWED,
            counted=True,
            outcome="pending",
            occurred_at_ms=resolved_attempt.context.occurred_at_ms,
        )
        return AccountControlAttempt(self, event_index)

    def _should_track_symbol_scope(self, *, operation: str, symbol: str | None) -> bool:
        if symbol is None:
            return False
        return self._get_effective_symbol_scope(operation=operation, symbol=symbol) is not None

    def _apply_allowed_side_effects(
        self,
        *,
        operation: str,
        symbol: str | None,
        window: AccountControlWindow,
        occurred_at_ms: int,
        track_symbol_scope: bool,
    ) -> None:
        self._increment_operation_counters(
            operation=operation,
            symbol=symbol,
            window=window,
            track_symbol_scope=track_symbol_scope,
        )
        self._record_allowed_timestamps(
            operation=operation,
            symbol=symbol,
            occurred_at_ms=occurred_at_ms,
            track_symbol_scope=track_symbol_scope,
        )
        self._record_group_allowance(operation=operation, window=window, occurred_at_ms=occurred_at_ms)

    def _record_allowed_timestamps(
        self,
        *,
        operation: str,
        symbol: str | None,
        occurred_at_ms: int,
        track_symbol_scope: bool,
    ) -> None:
        self._set_last_allowed_at_ms(operation=operation, occurred_at_ms=occurred_at_ms, symbol=None)
        if track_symbol_scope and symbol is not None:
            self._set_last_allowed_at_ms(operation=operation, occurred_at_ms=occurred_at_ms, symbol=symbol)

    def _record_group_allowance(
        self,
        *,
        operation: str,
        window: AccountControlWindow,
        occurred_at_ms: int,
    ) -> None:
        for group_key in self._get_operation_group_keys(operation):
            self._increment_group_counters(group_key=group_key, window=window)
            self._set_group_last_allowed_at_ms(group_key=group_key, occurred_at_ms=occurred_at_ms)

    def _append_operation_event(
        self,
        *,
        operation: str,
        symbol: str | None,
        metadata: Mapping[str, object] | None,
        control_date: str,
        decision: AccountControlDecision,
        counted: bool,
        outcome: str,
        occurred_at_ms: int,
    ) -> int:
        seq = self._next_event_seq()
        self._events.append(
            AccountControlEventWrite(
                account_id=self.account_id,
                control_date=control_date,
                execution_id=self.execution_id,
                seq=seq,
                channel=self.channel,
                operation=operation,
                symbol=symbol,
                metadata=_normalize_metadata(metadata),
                decision=decision,
                counted=counted,
                outcome=outcome,
                event_uid=self._build_event_uid(seq, operation, symbol, decision),
                occurred_at_ms=occurred_at_ms,
            )
        )
        return len(self._events) - 1

    def _build_counter_deltas(self) -> list[AccountControlCounterDeltaWrite]:
        return [
            *self._build_account_counter_deltas(),
            *self._build_symbol_counter_deltas(),
        ]

    def _build_account_counter_deltas(self) -> list[AccountControlCounterDeltaWrite]:
        counter_deltas: list[AccountControlCounterDeltaWrite] = []
        for key in sorted(self._account_counters, key=lambda item: (item[0], item[1].value, item[2], item[3])):
            control_date, bucket_type, bucket_start, operation = key
            delta_count = self._account_counters[key]
            counter_deltas.append(
                AccountControlCounterDeltaWrite(
                    account_id=self.account_id,
                    execution_id=self.execution_id,
                    control_date=control_date,
                    bucket_type=bucket_type,
                    bucket_start=bucket_start,
                    scope_type=AccountControlScopeType.ACCOUNT,
                    symbol=None,
                    operation=operation,
                    delta_count=delta_count,
                    delta_uid=(
                        f"{self.execution_id}:{control_date}:{bucket_type.value}:{bucket_start}:"
                        f"{AccountControlScopeType.ACCOUNT.value}:-:{operation}"
                    ),
                )
            )
        return counter_deltas

    def _build_symbol_counter_deltas(self) -> list[AccountControlCounterDeltaWrite]:
        counter_deltas: list[AccountControlCounterDeltaWrite] = []
        for key in sorted(
            self._symbol_counters,
            key=lambda item: (item[0], item[1], item[2].value, item[3], item[4]),
        ):
            control_date, symbol, bucket_type, bucket_start, operation = key
            delta_count = self._symbol_counters[key]
            counter_deltas.append(
                AccountControlCounterDeltaWrite(
                    account_id=self.account_id,
                    execution_id=self.execution_id,
                    control_date=control_date,
                    bucket_type=bucket_type,
                    bucket_start=bucket_start,
                    scope_type=AccountControlScopeType.SYMBOL,
                    symbol=symbol,
                    operation=operation,
                    delta_count=delta_count,
                    delta_uid=(
                        f"{self.execution_id}:{control_date}:{bucket_type.value}:{bucket_start}:"
                        f"{AccountControlScopeType.SYMBOL.value}:{symbol}:{operation}"
                    ),
                )
            )
        return counter_deltas

    def _evaluate_enforcement(
        self,
        *,
        operation: str,
        symbol: str | None,
        context: AccountControlEvaluationContext,
    ) -> AccountControlEnforcementDecision:
        assert self.policy is not None
        operation_policy = self.policy.operations.get(operation, AccountControlOperationPolicy())
        decisions = [
            self._check_scope_limits(
                scope_policy=operation_policy.account,
                scope_key=operation,
                context=context,
                symbol=None,
                message_symbol=symbol,
                is_group=False,
            )
        ]

        effective_symbol_scope = self._get_effective_symbol_scope(operation=operation, symbol=symbol)
        if symbol is not None and effective_symbol_scope is not None:
            decisions.append(
                self._check_scope_limits(
                    scope_policy=effective_symbol_scope,
                    scope_key=operation,
                    context=context,
                    symbol=symbol,
                    message_symbol=symbol,
                    is_group=False,
                )
            )

        for group_key in self._get_operation_group_keys(operation):
            group_policy = self.policy.groups.get(group_key)
            if group_policy is None:
                continue
            decisions.append(
                self._check_scope_limits(
                    scope_policy=group_policy,
                    scope_key=group_key,
                    context=context,
                    symbol=None,
                    message_symbol=symbol,
                    is_group=True,
                )
            )

        return self._combine_decisions(decisions)

    def _combine_decisions(
        self,
        decisions: list[AccountControlEnforcementDecision],
    ) -> AccountControlEnforcementDecision:
        max_wait_ms = 0
        for decision in decisions:
            if decision.kind == "block":
                return decision
            if decision.kind == "wait":
                max_wait_ms = max(max_wait_ms, decision.wait_ms)
        if max_wait_ms > 0:
            return AccountControlEnforcementDecision.wait(max_wait_ms)
        return AccountControlEnforcementDecision.allow()

    def _get_effective_symbol_scope(
        self,
        *,
        operation: str,
        symbol: str | None,
    ) -> AccountControlScopePolicy | None:
        if symbol is None or self.policy is None:
            return None
        operation_policy = self.policy.operations.get(operation)
        return None if operation_policy is None else _copy_scope_policy(operation_policy.symbol)

    def _check_scope_limits(
        self,
        *,
        scope_policy: AccountControlScopePolicy,
        scope_key: str,
        context: AccountControlEvaluationContext,
        symbol: str | None,
        message_symbol: str | None,
        is_group: bool,
    ) -> AccountControlEnforcementDecision:
        day_rule = scope_policy.per_day
        if day_rule is not None:
            day_count = self._get_count(
                control_date=context.window.control_date,
                bucket_type=AccountControlBucketType.DAY,
                bucket_start=context.window.day_bucket_start,
                scope_key=scope_key,
                symbol=symbol,
                is_group=is_group,
            )
            if day_count >= day_rule.limit:
                target = message_symbol or "account"
                decision = self._decision_for_trigger(
                    rule_kind="per_day",
                    on_trigger=day_rule.on_trigger,
                    wait_ms=self._get_wait_ms_until_next_day(context.local_now),
                    target=target,
                    operation_or_group=scope_key,
                )
                if decision.kind != "allow":
                    return decision

        max_wait_ms = 0
        minute_rule = scope_policy.per_minute
        if minute_rule is not None:
            minute_count = self._get_count(
                control_date=context.window.control_date,
                bucket_type=AccountControlBucketType.MINUTE,
                bucket_start=context.window.minute_bucket_start,
                scope_key=scope_key,
                symbol=symbol,
                is_group=is_group,
            )
            if minute_count >= minute_rule.limit:
                if minute_rule.limit == 0:
                    target = message_symbol or "account"
                    return AccountControlEnforcementDecision.block(
                        f"账户风控拦截 {target} {scope_key}：每分钟频率已达上限",
                        "policy_blocked",
                    )
                decision = self._decision_for_trigger(
                    rule_kind="per_minute",
                    on_trigger=minute_rule.on_trigger,
                    wait_ms=self._get_wait_ms_until_next_minute(context.local_now),
                    target=message_symbol or "account",
                    operation_or_group=scope_key,
                )
                if decision.kind == "block":
                    return decision
                if decision.kind == "wait":
                    max_wait_ms = max(max_wait_ms, decision.wait_ms)

        interval_rule = scope_policy.min_interval_ms
        if interval_rule is not None:
            last_allowed_at_ms = self._get_last_allowed_at_ms(
                scope_key=scope_key,
                symbol=symbol,
                is_group=is_group,
            )
            if last_allowed_at_ms is not None:
                remaining_ms = interval_rule.limit - (context.occurred_at_ms - last_allowed_at_ms)
                if remaining_ms > 0:
                    decision = self._decision_for_trigger(
                        rule_kind="min_interval_ms",
                        on_trigger=interval_rule.on_trigger,
                        wait_ms=remaining_ms,
                        target=message_symbol or "account",
                        operation_or_group=scope_key,
                    )
                    if decision.kind == "block":
                        return decision
                    if decision.kind == "wait":
                        max_wait_ms = max(max_wait_ms, decision.wait_ms)

        if max_wait_ms > 0:
            return AccountControlEnforcementDecision.wait(max_wait_ms)
        return AccountControlEnforcementDecision.allow()

    def _decision_for_trigger(
        self,
        *,
        rule_kind: str,
        on_trigger: AccountControlTriggerBehavior,
        wait_ms: int,
        target: str,
        operation_or_group: str,
    ) -> AccountControlEnforcementDecision:
        if on_trigger == AccountControlTriggerBehavior.BLOCK:
            return AccountControlEnforcementDecision.block(
                f"账户风控拦截 {target} {operation_or_group}：{rule_kind} 已达限额",
                "policy_blocked",
            )
        if wait_ms <= 0:
            return AccountControlEnforcementDecision.allow()
        return AccountControlEnforcementDecision.wait(wait_ms)

    def _get_wait_ms_until_next_minute(self, local_now: datetime) -> int:
        next_minute = local_now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return max(int((next_minute - local_now).total_seconds() * 1000), 0)

    def _get_wait_ms_until_next_day(self, local_now: datetime) -> int:
        next_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return max(int((next_day - local_now).total_seconds() * 1000), 0)

    def _wait_for_quota(self, wait_ms: int, symbol: str | None) -> None:
        remaining_ms = wait_ms
        while remaining_ms > 0:
            self._run_termination_checkpoint(symbol)
            sleep_ms = min(remaining_ms, self._wait_poll_interval_ms)
            self._sleep(sleep_ms / 1000)
            remaining_ms -= sleep_ms
        self._run_termination_checkpoint(symbol)

    def _run_termination_checkpoint(self, symbol: str | None) -> None:
        if self._termination_checkpoint is None:
            return
        self._termination_checkpoint(symbol)

    def _get_count(
        self,
        *,
        control_date: str,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        scope_key: str,
        symbol: str | None,
        is_group: bool,
    ) -> int:
        if is_group:
            return self._get_group_count(
                control_date=control_date,
                bucket_type=bucket_type,
                bucket_start=bucket_start,
                group_key=scope_key,
            )

        baseline = 0
        if control_date == self._baseline_control_date:
            baseline = self.baseline.get_count(
                bucket_type=bucket_type,
                bucket_start=bucket_start,
                operation=scope_key,
                symbol=symbol,
            )
        if symbol is None:
            return baseline + self._account_counters.get((control_date, bucket_type, bucket_start, scope_key), 0)
        return baseline + self._symbol_counters.get((control_date, symbol, bucket_type, bucket_start, scope_key), 0)

    def _get_group_count(
        self,
        *,
        control_date: str,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        group_key: str,
    ) -> int:
        baseline = 0
        if control_date == self._baseline_control_date:
            for operation_key in self._get_group_operation_keys(group_key):
                baseline += self.baseline.get_count(
                    bucket_type=bucket_type,
                    bucket_start=bucket_start,
                    operation=operation_key,
                )
        return baseline + self._group_counters.get((control_date, bucket_type, bucket_start, group_key), 0)

    def _increment_operation_counters(
        self,
        *,
        operation: str,
        symbol: str | None,
        window: AccountControlWindow,
        track_symbol_scope: bool,
    ) -> None:
        self._increment_account_counter(
            window.control_date, AccountControlBucketType.MINUTE, window.minute_bucket_start, operation
        )
        self._increment_account_counter(
            window.control_date, AccountControlBucketType.DAY, window.day_bucket_start, operation
        )
        if track_symbol_scope and symbol is not None:
            self._increment_symbol_counter(
                window.control_date,
                symbol,
                AccountControlBucketType.MINUTE,
                window.minute_bucket_start,
                operation,
            )
            self._increment_symbol_counter(
                window.control_date,
                symbol,
                AccountControlBucketType.DAY,
                window.day_bucket_start,
                operation,
            )

    def _increment_group_counters(
        self,
        *,
        group_key: str,
        window: AccountControlWindow,
    ) -> None:
        self._increment_group_counter(
            window.control_date, AccountControlBucketType.MINUTE, window.minute_bucket_start, group_key
        )
        self._increment_group_counter(
            window.control_date, AccountControlBucketType.DAY, window.day_bucket_start, group_key
        )

    def _increment_account_counter(
        self,
        control_date: str,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        operation: str,
    ) -> None:
        key = (control_date, bucket_type, bucket_start, operation)
        self._account_counters[key] = self._account_counters.get(key, 0) + 1

    def _increment_symbol_counter(
        self,
        control_date: str,
        symbol: str,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        operation: str,
    ) -> None:
        key = (control_date, symbol, bucket_type, bucket_start, operation)
        self._symbol_counters[key] = self._symbol_counters.get(key, 0) + 1

    def _increment_group_counter(
        self,
        control_date: str,
        bucket_type: AccountControlBucketType,
        bucket_start: str,
        group_key: str,
    ) -> None:
        key = (control_date, bucket_type, bucket_start, group_key)
        self._group_counters[key] = self._group_counters.get(key, 0) + 1

    def _get_last_allowed_at_ms(
        self,
        *,
        scope_key: str,
        symbol: str | None,
        is_group: bool,
    ) -> int | None:
        if is_group:
            return self._get_group_last_allowed_at_ms(scope_key)
        if symbol is None:
            return self._recent_account_allowed_at.get((scope_key,))
        return self._recent_symbol_allowed_at.get((symbol, scope_key))

    def _set_last_allowed_at_ms(
        self,
        *,
        operation: str,
        occurred_at_ms: int,
        symbol: str | None,
    ) -> None:
        if symbol is None:
            self._recent_account_allowed_at[(operation,)] = occurred_at_ms
            return
        self._recent_symbol_allowed_at[(symbol, operation)] = occurred_at_ms

    def _get_group_last_allowed_at_ms(self, group_key: str) -> int | None:
        values = [self._recent_group_allowed_at.get((group_key,))]
        for operation_key in self._get_group_operation_keys(group_key):
            values.append(self._recent_account_allowed_at.get((operation_key,)))
        filtered = [value for value in values if value is not None]
        if not filtered:
            return None
        return max(filtered)

    def _set_group_last_allowed_at_ms(self, *, group_key: str, occurred_at_ms: int) -> None:
        self._recent_group_allowed_at[(group_key,)] = occurred_at_ms

    def _get_group_operation_keys(self, group_key: str) -> list[str]:
        return [
            operation_key
            for operation_key, operation in self._registry.operations.items()
            if group_key in operation.groups
        ]

    def _get_operation_group_keys(self, operation: str) -> tuple[str, ...]:
        registered_operation = self._registry.get_operation(operation)
        if registered_operation is None:
            return ()
        return tuple(sorted(registered_operation.groups))

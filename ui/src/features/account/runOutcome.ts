import { executionOutcome } from '@/features/account/executionOutcome'
import type { ExecutionStatus } from '@/types/api'

export type RunKind = 'exec' | 'clear'

export type RunOutcome =
  | { kind: 'success'; toast: string }
  | { kind: 'blocked'; toast: string }
  | { kind: 'not_reached' | 'unknown'; toast: string }
  | { kind: 'terminated'; toast: string }
  | { kind: 'failed'; error: string }

/**
 * 把明确的执行结论翻成 toast 意图。
 *
 * 不依赖用于调度的任务状态或输出状态。
 * ``failed`` 不弹 toast：账户状态行 / 近期执行已经承接同一次结果。
 */
export function describeRunOutcome(
  kind: RunKind,
  conclusion?: Pick<ExecutionStatus, 'outcome' | 'outcome_reason' | 'outcome_symbols'>,
): RunOutcome {
  const view = executionOutcome(conclusion, kind === 'clear')
  if (view.outcome === 'error') return { kind: 'failed', error: view.text }
  if (view.outcome === 'completed') return { kind: 'success', toast: view.text }
  if (view.outcome === 'blocked' || view.outcome === 'terminated' || view.outcome === 'not_reached') return { kind: view.outcome, toast: view.text }
  return { kind: 'unknown', toast: view.text }
}

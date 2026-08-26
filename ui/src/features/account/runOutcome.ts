import type { ExecutionStatus, ExecutionTaskStatus } from '@/types/api'

export type RunKind = 'exec' | 'clear'

export type RunOutcome =
  | { kind: 'success'; toast: string }
  | { kind: 'blocked'; toast: string }
  | { kind: 'terminated'; toast: string }
  | { kind: 'failed'; error: string }

/**
 * 把任务终态 + 执行器输出翻成 toast 意图.
 *
 * 任务 ``SUCCEEDED`` 只表示进程跑完。全员 ``BLOCKED`` 是约束，不是「已按目标到位」。
 * ``failed`` 不弹 toast：账户状态行 / 近期执行已经承接同一次结果。
 */
export function describeRunOutcome(
  kind: RunKind,
  status: ExecutionTaskStatus,
  outputStatus: ExecutionStatus['output_status'],
  error: string | null | undefined,
): RunOutcome {
  if (status === 'TERMINATED') return { kind: 'terminated', toast: '执行已终止' }
  if (outputStatus === 'BLOCKED') {
    return { kind: 'blocked', toast: '非交易时段，未下单' }
  }
  if (status === 'FAILED') {
    const text = typeof error === 'string' && error.trim() ? error : '执行失败，服务端未返回原因'
    return { kind: 'failed', error: text }
  }
  return { kind: 'success', toast: kind === 'exec' ? '执行完成 · 已按目标到位' : '已清仓' }
}

import type { TargetWeightSnapshot } from '@/types/api'

/** 把目标快照时间、来源与计算上下文整理成稳定元信息。 */
export function targetSnapshotText(snapshot: TargetWeightSnapshot | null, contextName?: string | null): string {
  if (!snapshot?.calculated_at) return '尚无目标权重 · 点击刷新计算'
  const source = snapshot.source === 'execution' ? '实际执行' : '主动刷新'
  const context = contextName
    ? ` · 使用账户 ${contextName}`
    : snapshot.context_account_id == null
      ? ' · 样例上下文'
      : ''
  return `目标计算于 ${snapshot.calculated_at.replace('T', ' ')} · ${source}${context}`
}

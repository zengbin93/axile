import type { CostExecutionRow } from '@/lib/api/performance'
import type { ChartSelection } from '@/features/history/chartModel'
import { shanghaiTime } from '@/features/history/costs'

export function executionSelection(row: CostExecutionRow): Extract<ChartSelection, { kind: 'execution' }> {
  return { kind: 'execution', recordId: row.record.id, time: shanghaiTime(row.record.created_at) }
}

export function executionState(row: CostExecutionRow): string {
  if (row.record.raw_result.task_status === 'TERMINATED') return '已终止'
  if (row.record.is_success !== 1) return '执行失败'
  if (row.record.raw_result.status === 'PARTIAL') return '部分执行'
  if (row.noop) return row.positionCount === 0 ? '空仓 · 无需交易' : row.positionCount == null ? '未交易 · 持仓未知' : '持仓不变 · 无需交易'
  return row.positionCount === 0 ? '执行后空仓' : '执行完成'
}

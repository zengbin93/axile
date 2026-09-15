import { executionOutcome } from '@/features/account/executionOutcome'
import type { CostExecutionRow } from '@/lib/api/performance'
import type { ChartSelection } from '@/features/history/chartModel'
import { shanghaiTime } from '@/features/history/costs'

export function executionSelection(row: CostExecutionRow): Extract<ChartSelection, { kind: 'execution' }> {
  return { kind: 'execution', recordId: row.record.id, time: shanghaiTime(row.record.created_at) }
}

export function executionState(row: CostExecutionRow): string {
  return executionOutcome(row.record).text
}

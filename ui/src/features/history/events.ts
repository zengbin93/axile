import type { AccountActivity } from '@/lib/api/accounts'
import type { PortfolioAccountRecord } from '@/types/api'
import type { TimeWindow } from '@/features/account/executionJournal'
import { executionRecordError } from '@/features/account/executionRecordError'
import { shanghaiTime } from './costs'

export function performanceEvents(bindings: PortfolioAccountRecord[], activity: AccountActivity[], window: TimeWindow, names: Map<number, string>) {
  return [
    ...bindings.map(b => ({ time: b.created_at, tag: '换绑', text: b.portfolio_id == null ? '解绑组合' : names.get(b.portfolio_id) ?? `组合 #${b.portfolio_id}`, executionId: null as string | null })),
    ...activity.flatMap(a => a.kind === 'schedule_skip' ? [{ time: a.occurred_at, tag: '跳过', text: a.reason_code === 'BUSY' ? '执行中' : '休市', executionId: null as string | null }] : a.record.is_success !== 1 ? [{ time: a.occurred_at, tag: a.record.raw_result.task_status === 'TERMINATED' ? '终止' : '失败', text: executionRecordError(a.record) || '执行未完成', executionId: a.record.execution_id }] : []),
  ].filter(e => shanghaiTime(e.time) >= window.start && shanghaiTime(e.time) < window.end).sort((a, b) => shanghaiTime(b.time) - shanghaiTime(a.time))
}

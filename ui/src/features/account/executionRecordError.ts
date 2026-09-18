import { shortErrorReason } from '@/lib/errorInfo'

/** 执行记录顶层错误的人读短原因；无错误时返回空串。 */
export function executionRecordError(record: { error?: string | null; raw_result?: { error?: unknown; interrupt_reason?: unknown } }): string {
  const raw = record.raw_result
  if (raw?.interrupt_reason === 'process_interrupted') return '上次执行中断，未自动续跑'
  const value = raw?.error ?? record.error
  return typeof value === 'string' && value.trim() ? shortErrorReason(new Error(value)) : ''
}

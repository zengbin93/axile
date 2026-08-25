import type { ExecuteRecord } from '@/types/api'
import { shortErrorReason } from '@/lib/errorInfo'

/** 执行记录顶层错误的人读短原因；无错误时返回空串。 */
export function executionRecordError(record: ExecuteRecord): string {
  const value = (record.raw_result as { error?: unknown }).error
  return typeof value === 'string' && value.trim() ? shortErrorReason(new Error(value)) : ''
}

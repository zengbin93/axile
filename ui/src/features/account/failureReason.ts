/** 直接回放已有错误；不分类、归责或推荐重试。 */
import type { ExecutionEvent } from '@/types/api'
export interface FailureReason { human: string; raw: string }
export function describeFailureText(text: string): FailureReason { return { human: text, raw: text } }
export function describeFailure(event: ExecutionEvent | null | undefined): FailureReason | null {
  if (!event) return null
  const debug = event.details?.debug as { error?: unknown } | undefined
  const error = debug?.error
  const raw = typeof error === 'string' ? error : error && typeof error === 'object' && 'message' in error && typeof error.message === 'string' ? error.message : ''
  return describeFailureText(raw)
}

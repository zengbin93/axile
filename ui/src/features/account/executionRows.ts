/** 执行事件流 → 逐只结果行的纯函数（与抽屉组件解耦，便于测试与 fast-refresh）。 */
import type { ExecutionEvent } from '@/types/api'

/** 逐只结果行。 */
export interface SymbolRow {
  symbol: string
  status: string
  reason: string
}

/** 从事件 details 里取品种级错误串（后端写在 `details.debug.error`）。 */
export function eventError(e: ExecutionEvent): string {
  const debug = (e.details as { debug?: unknown } | undefined)?.debug
  if (debug && typeof debug === 'object' && 'error' in debug) {
    const err = (debug as { error?: unknown }).error
    if (typeof err === 'string') return err
  }
  return ''
}

/** 执行级（非逐只）问题提示：来自 EXECUTION_FAILED 等生命周期事件。 */
export interface LifecycleNote {
  status: string
  text: string
}

/**
 * 从事件流里挑出执行级 ERROR/WARNING 提示（排除逐只事件，避免与 symbolRows 重复）。
 *
 * 用于覆盖「在进入 symbol 调度前就失败」的场景——此时没有逐只行，真实原因躺在
 * `EXECUTION_FAILED` 的 `details.debug.error` 里，需要单独显出来。
 */
export function lifecycleNotes(events: ExecutionEvent[]): LifecycleNote[] {
  const notes: LifecycleNote[] = []
  for (const e of events) {
    if (e.event_type === 'symbol_decision_made' || e.event_type === 'symbol_skipped') continue
    if (e.status !== 'ERROR' && e.status !== 'WARNING') continue
    const text = eventError(e)
    if (text) notes.push({ status: e.status, text })
  }
  return notes
}

/** 从事件流里挑出「逐只决策/跳过」事件，聚合成 symbol 级结果行（含错误原因）。 */
export function symbolRows(events: ExecutionEvent[]): SymbolRow[] {
  const rows: SymbolRow[] = []
  for (const e of events) {
    if (e.event_type !== 'symbol_decision_made' && e.event_type !== 'symbol_skipped') continue
    if (!e.symbol) continue
    const err = eventError(e)
    const reason = err || (e.event_type === 'symbol_skipped' ? e.reason_code || '跳过' : '')
    rows.push({ symbol: e.symbol, status: e.status, reason })
  }
  return rows
}

/** 展示结论只接受新记录的明确证据，不回推旧状态。 */
export type ExecutionOutcome = 'completed' | 'not_reached' | 'error' | 'terminated' | 'blocked' | 'unknown' | 'legacy'
export interface OutcomeView {
  outcome: ExecutionOutcome
  text: string
  reason: string
  warning: boolean
  symbols: string[]
}
const OUTCOMES = new Set(['completed', 'not_reached', 'error', 'terminated', 'blocked', 'unknown'])
const dict = (v: unknown): Record<string, unknown> => v && typeof v === 'object' ? v as Record<string, unknown> : {}
export function outcomeOf(value: unknown): ExecutionOutcome {
  return typeof value === 'string' && OUTCOMES.has(value) ? value as ExecutionOutcome : 'legacy'
}
export function symbolPreview(symbols: string[]): string {
  return symbols.slice(0, 3).join('、') + (symbols.length > 3 ? ` 等 ${symbols.length} 个品种` : '')
}
export function executionOutcome(value: unknown, clear = false): OutcomeView {
  const raw = dict(value)
  const outcome = outcomeOf(raw.outcome)
  const symbols = Array.isArray(raw.outcome_symbols)
    ? raw.outcome_symbols.filter((s): s is string => typeof s === 'string')
    : Object.entries(dict(raw.symbol_results)).filter(([, v]) => ['not_reached', 'blocked'].includes(String(dict(v).outcome))).map(([symbol]) => symbol)
  const reason = typeof raw.outcome_reason === 'string' ? raw.outcome_reason.trim() : ''
  const label = {
    completed: clear || raw.execution_kind === 'clear_positions' ? '清仓完成' : '执行完成',
    not_reached: '执行不到位', error: '执行失败', terminated: '执行已终止',
    blocked: '未执行', unknown: '执行结果待确认', legacy: '历史执行记录',
  }[outcome]
  const detail = outcome === 'not_reached' ? symbolPreview(symbols) : outcome === 'error' || outcome === 'blocked' ? reason : ''
  return { outcome, symbols, reason, text: detail ? `${label} · ${detail}` : label, warning: ['not_reached', 'error', 'unknown'].includes(outcome) }
}

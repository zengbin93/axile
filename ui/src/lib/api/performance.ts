import { apiGet, apiSend } from '@/lib/api/client'
import type { AccountPerformance, PerformanceSettings } from '@/types/api'
import type { CostSummary, CostTrade } from '@/features/history/costs'
import type { ChartSelection } from '@/features/history/chartModel'

export type PerformanceRange = '30' | '90' | 'all'
export interface PerformanceSnapshot {
  status: 'empty' | 'pending' | 'ready' | 'stale' | 'failed'
  source_version: number
  snapshot_id: string | null
  snapshot_version: number | null
  logic_version: string
  engine_version: string
  computed_at: string | null
  data_until: string | null
  settings: PerformanceSettings | null
  error: string | null
  retry_at: number | null
  result: AccountPerformance | null
  daily_costs: Record<string, CostSummary>
  events: { time: string; tag: string; text: string; executionId: string | null }[]
  event_count: number
}
export interface CostExecutionRow {
  key: string
  record: { id: number; execution_id: string | null; created_at: string; is_success: number; raw_result: { status?: string; task_status?: string } }
  noop: boolean
  symbolCount: number
  positionCount?: number | null
  positions?: Array<{ symbol: string; quantity: number; direction: string }> | null
  transactions?: TransactionPreview[]
  reason?: string
  attempts?: Array<{ symbol: string; planned: number | null; filled: number | null; reason: string }>
  summary: CostSummary
}
export interface TransactionPreview {
  symbol: string
  side: 'buy' | 'sell' | 'none'
  quantity: number
  price: number | null
  reference: number | null
  referenceSource: 'mid' | 'last' | null
  time: number
  endTime: number
  timeEstimated: boolean
  before: number | null
  target: number | null
  summary: CostSummary
}
export interface CostSymbolRow { symbol: string; summary: CostSummary; buy: number; sell: number; quantityIncomplete: boolean }
export interface CostPage<T = CostExecutionRow | CostSymbolRow | CostTrade> {
  snapshot_id: string
  summary: CostSummary & { estimated: number }
  successful: number
  noop: number
  count: number
  data: T[]
  next_cursor: string | null
}
export interface CostQuery {
  snapshot_id: string
  range: PerformanceRange
  dimension: 'execution' | 'symbol' | 'trade' | 'summary'
  sort?: 'time' | 'cost'
  day?: string
  start?: number
  end?: number
  record_id?: number
  symbol?: string
  cursor?: string
}
export function selectionQuery(selection: ChartSelection) {
  return selection?.kind === 'execution' ? { record_id: selection.recordId } : selection?.kind === 'day' ? { day: selection.day } : selection?.kind === 'interval' ? { start: selection.start, end: selection.end } : {}
}
export const getPerformanceSnapshot = (id: number, range: PerformanceRange) => apiGet<PerformanceSnapshot>(`/account/performance/${id}/snapshot?range=${range}`)
export const refreshPerformance = (id: number) => apiSend('POST', `/account/performance/${id}/refresh`)
export function getPerformanceCosts<T = CostExecutionRow | CostSymbolRow | CostTrade>(id: number, query: CostQuery, signal?: AbortSignal) {
  const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value != null).map(([key, value]) => [key, String(value)]))
  return apiGet<CostPage<T>>(`/account/performance/${id}/costs?${params}`, signal)
}

export function getPerformance(id: number, range: '30' | '90' | 'all', signal?: AbortSignal, includeBacktest = true) {
  return apiGet<AccountPerformance>(`/account/performance/${id}?range=${range}&include_backtest=${includeBacktest}`, signal)
}

export function savePerformanceSettings(id: number, settings: PerformanceSettings) {
  return apiSend<PerformanceSettings>('PATCH', `/account/performance-settings/${id}`, settings)
}

import type { AccountActivity, AccountActivityList } from '@/lib/api/accounts'
import type { ExecuteRecord } from '@/types/api'
import { dict, loadJournal, number, sideOf, type TimeWindow } from '@/features/account/executionJournal'

export const amount = (value: number | null) => value == null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: Math.abs(value) < 0.01 ? 8 : 2 })
export const quantityText = (value: number | null) => value == null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 8 })
export const feeText = (summary: CostSummary) => Object.entries(summary.fees).map(([currency, value]) => `${amount(value)} ${currency}`).join(' · ') || '—'
export const coverageText = (summary: CostSummary) => summary.coverage == null
  ? `${summary.covered}/${summary.count} 笔有效` : `${(summary.coverage * 100).toFixed(1)}% 成交额覆盖`

/** 无快照游标的活动流，完整复读校验同数量原地更新；两遍一致才发布。 */
export async function loadPerformanceActivity(accountId: number, window: TimeWindow, signal: AbortSignal, fetchPage?: (skip: number) => Promise<AccountActivityList>) {
  const first = await loadJournal(accountId, window, signal, fetchPage, shanghaiTime)
  const second = await loadJournal(accountId, window, signal, fetchPage, shanghaiTime)
  if (JSON.stringify(first) !== JSON.stringify(second)) throw new Error('执行记录在加载期间发生变化，请刷新重试')
  return second
}

export function shanghaiTime(value: string): number {
  const iso = value.replace(' ', 'T')
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}+08:00`)
}

export function shanghaiDay(value: string): string {
  return new Date(shanghaiTime(value) + 8 * 3600000).toISOString().slice(0, 10)
}

export function shanghaiLabel(value: string): string {
  return new Date(shanghaiTime(value) + 8 * 3600000).toISOString().slice(0, 19).replace('T', ' ')
}

export interface CostTrade {
  symbol: string
  day: string
  time: number
  timeEstimated: boolean
  side: 'buy' | 'sell' | 'none'
  quantity: number | null
  price: number | null
  reference: number | null
  referenceSource: 'mid' | 'last' | null
  value: number | null
  cost: number | null
  lossBp: number | null
  fee: number | null
  feeCurrency: string | null
}

export interface CostSummary {
  value: number | null
  cost: number | null
  lossBp: number | null
  coverage: number | null
  covered: number
  count: number
  amountComplete: boolean
  fees: Record<string, number>
  feeCovered: number
}

const positive = (value: unknown) => { const n = number(value); return n != null && n > 0 ? n : null }

export function costTrades(record: ExecuteRecord): CostTrade[] {
  return Object.entries(dict(record.raw_result.symbol_results)).flatMap(([symbol, raw]) => {
    const result = dict(raw)
    const tick = dict(result.first_tick)
    const bid = positive(tick.bid_price), ask = positive(tick.ask_price)
    const mid = bid != null && ask != null && ask >= bid ? (bid + ask) / 2 : null
    const reference = mid ?? positive(tick.last_price)
    const multiplier = positive(dict(result.sizing).unit_multiplier)
    const orders = new Map((Array.isArray(result.orders) ? result.orders : []).map(rawOrder => {
      const order = dict(rawOrder)
      return [String(order.order_id), sideOf(order.direction)]
    }))
    return (Array.isArray(result.trades) ? result.trades : []).map(rawTrade => {
      const trade = dict(rawTrade), extra = dict(trade.extra)
      const price = positive(trade.trade_price), quantity = positive(trade.trade_volume)
      const orderSide = orders.get(String(trade.order_id))
      const side = orderSide && orderSide !== 'none' ? orderSide : sideOf(extra.direction)
      const value = price != null && quantity != null && multiplier != null ? price * quantity * multiplier : null
      const cost = value != null && reference != null && side !== 'none'
        ? (side === 'buy' ? 1 : -1) * (price! - reference) * quantity! * multiplier! : null
      const actualTime = typeof trade.trade_time === 'string' && trade.trade_time.trim() ? shanghaiTime(trade.trade_time) : NaN
      const timeEstimated = !Number.isFinite(actualTime)
      const time = timeEstimated ? shanghaiTime(record.created_at) : actualTime
      return { symbol, day: new Date(time + 8 * 3600000).toISOString().slice(0, 10), time, timeEstimated,
        side, quantity, price, reference, referenceSource: mid != null ? 'mid' as const : reference != null ? 'last' as const : null,
        value, cost, lossBp: reference != null && price != null && side !== 'none' ? (price - reference) / reference * 1e4 * (side === 'buy' ? 1 : -1) : null,
        fee: number(extra.commission), feeCurrency: typeof extra.commission_asset === 'string' && extra.commission_asset.trim() ? extra.commission_asset : null }
    })
  })
}

export function summarizeCosts(trades: CostTrade[]): CostSummary {
  const valued = trades.filter(t => t.value != null)
  const valid = trades.filter(t => t.cost != null && t.value != null)
  const value = valued.reduce((sum, t) => sum + t.value!, 0)
  const coveredValue = valid.reduce((sum, t) => sum + t.value!, 0)
  const fees: Record<string, number> = {}
  let feeCovered = 0
  for (const trade of trades) if (trade.fee != null && trade.feeCurrency) {
    fees[trade.feeCurrency] = (fees[trade.feeCurrency] ?? 0) + trade.fee
    feeCovered++
  }
  return { value: valued.length ? value : null, cost: valid.length ? valid.reduce((sum, t) => sum + t.cost!, 0) : null,
    lossBp: coveredValue > 0 ? valid.reduce((sum, t) => sum + t.lossBp! * t.value!, 0) / coveredValue : null,
    coverage: valued.length === trades.length && value > 0 ? coveredValue / value : null,
    covered: valid.length, count: trades.length, amountComplete: valued.length === trades.length, fees, feeCovered }
}

export interface CostExecution {
  key: string
  record: ExecuteRecord
  trades: CostTrade[]
  summary: CostSummary
  noop: boolean
}

export function executionsOnDay(executions: CostExecution[], day: string | null): CostExecution[] {
  if (!day) return executions
  return executions.flatMap(e => {
    const trades = e.trades.filter(t => t.day === day)
    return trades.length || shanghaiDay(e.record.created_at) === day ? [{ ...e, trades, summary: summarizeCosts(trades) }] : []
  })
}

export function costExecutions(activity: AccountActivity[]): CostExecution[] {
  return activity.flatMap(a => {
    if (a.kind !== 'execution') return []
    const trades = costTrades(a.record)
    const results = Object.values(dict(a.record.raw_result.symbol_results)).map(dict)
    const hasOrderFill = results.some(r => (Array.isArray(r.orders) ? r.orders : []).some(o => (number(dict(o).filled_volume) ?? 0) > 0))
    const noop = a.record.is_success === 1 && !trades.length && !hasOrderFill &&
      (a.record.raw_result.status === 'NOOP' || (results.length > 0 && results.every(r => r.status === 'NOOP')))
    return [{ key: String(a.record.id ?? a.record.execution_id), record: a.record, trades, summary: summarizeCosts(trades), noop }]
  })
}

export function dailyCosts(executions: CostExecution[]): Map<string, CostSummary> {
  const groups = new Map<string, CostTrade[]>()
  for (const execution of executions) for (const trade of execution.trades) {
    const group = groups.get(trade.day) ?? []
    group.push(trade)
    groups.set(trade.day, group)
  }
  return new Map([...groups].map(([day, trades]) => [day, summarizeCosts(trades)]))
}

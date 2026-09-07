import { getAccountActivity, type AccountActivity, type AccountActivityList } from '@/lib/api/accounts'
import { buildRecentActivity, recentRowText } from '@/features/account/recent'

type Dict = Record<string, unknown>
export type JournalRange = '7' | '30' | '90' | 'custom'
export interface TimeWindow { start: number; end: number }
export interface JournalTrade {
  key: string
  executionId: string | null
  symbol: string
  time: string
  side: 'buy' | 'sell' | 'none'
  price: number
  volume: number
  value: number | null
  slippageBps: number | null
}
export interface Quality {
  value: number
  nTrades: number
  slippage: number | null
  coverage: number
  amountComplete: boolean
}
export interface JournalExecution {
  key: string
  time: string
  executionId: string | null
  status: string
  warning: boolean
  description: string
  symbols: string[]
  trades: JournalTrade[]
}
export interface JournalSymbol extends Quality {
  symbol: string
  lastTime: string
  trades: JournalTrade[]
}

export function journalAmount(value: number): string { return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }
export function journalTime(value: string): string { return value.replace('T', ' ').slice(0, 16) }

function dict(value: unknown): Dict {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Dict : {}
}
function number(value: unknown): number | null {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}
function string(value: unknown): string { return typeof value === 'string' ? value : '' }
function sideOf(value: unknown): JournalTrade['side'] {
  const side = string(value).toLowerCase()
  return side === 'buy' || side === 'sell' ? side : 'none'
}

/** 日期范围按本地日历日计算；结束日包含全天。 */
export function journalWindow(range: JournalRange, from: string, to: string, now = new Date()): TimeWindow | null {
  const start = range === 'custom' ? new Date(`${from}T00:00:00`) : new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const end = range === 'custom' ? new Date(`${to}T00:00:00`) : new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (range !== 'custom') start.setDate(start.getDate() - Number(range) + 1)
  end.setDate(end.getDate() + 1)
  return Number.isFinite(+start) && Number.isFinite(+end) && +start < +end ? { start: +start, end: +end } : null
}

/** 统一活动流按时间倒序分页；读到区间下界才停止，失败不返回半份汇总。 */
export async function loadJournal(
  accountId: number,
  window: TimeWindow,
  signal: AbortSignal,
  fetchPage: (skip: number) => Promise<AccountActivityList> = (skip) => getAccountActivity(accountId, { skip, limit: 500 }, signal),
): Promise<AccountActivity[]> {
  const result: AccountActivity[] = []
  const seen = new Set<string>()
  let count: number | null = null
  for (let skip = 0; ; ) {
    signal.throwIfAborted()
    const page = await fetchPage(skip)
    signal.throwIfAborted()
    if (count != null && count !== page.count) throw new Error('执行记录在加载期间发生变化，请刷新重试')
    count = page.count
    if (!page.data.length && skip < count) throw new Error('执行记录分页不完整，请重试')
    for (const activity of page.data) {
      const key = activity.kind === 'execution' ? `execution:${activity.record.id ?? activity.record.execution_id}` : `skip:${activity.id}`
      if (seen.has(key)) throw new Error('执行记录分页发生重叠，请刷新重试')
      seen.add(key)
      const time = +new Date(activity.occurred_at)
      if (!Number.isFinite(time)) throw new Error('执行记录时间无效，无法确认统计范围')
      if (time >= window.start && time < window.end) result.push(activity)
    }
    skip += page.data.length
    if (skip >= count || page.data.some((a) => +new Date(a.occurred_at) < window.start)) return result
  }
}

/** 只读成交及参考价，不推测手续费、方向或缺失的成交金额。 */
function parseTrades(activity: AccountActivity): JournalTrade[] {
  if (activity.kind !== 'execution') return []
  const record = activity.record
  const trades: JournalTrade[] = []
  for (const [symbol, raw] of Object.entries(dict(record.raw_result.symbol_results))) {
    const result = dict(raw)
    const tick = dict(result.first_tick)
    const bid = number(tick.bid_price)
    const ask = number(tick.ask_price)
    const last = number(tick.last_price)
    const mid = bid != null && ask != null && bid > 0 && ask > bid ? (bid + ask) / 2 : last != null && last > 0 ? last : null
    const sides = new Map<string, JournalTrade['side']>()
    for (const rawOrder of Array.isArray(result.orders) ? result.orders : []) {
      const order = dict(rawOrder)
      if (string(order.order_id)) sides.set(string(order.order_id), sideOf(order.direction))
    }
    for (const [index, rawTrade] of (Array.isArray(result.trades) ? result.trades : []).entries()) {
      const trade = dict(rawTrade)
      const price = number(trade.trade_price)
      const volume = number(trade.trade_volume)
      if (price == null || price <= 0 || volume == null || volume <= 0) continue
      const orderSide = sides.get(string(trade.order_id))
      const side = orderSide && orderSide !== 'none' ? orderSide : sideOf(dict(trade.extra).direction)
      const value = number(trade.trade_value)
      trades.push({
        key: `${record.id ?? record.execution_id}:${symbol}:${index}`,
        executionId: record.execution_id,
        symbol, time: string(trade.trade_time) || record.created_at,
        side, price, volume, value: value != null && value >= 0 ? value : null,
        slippageBps: mid != null && side !== 'none' ? (price - mid) / mid * 1e4 * (side === 'buy' ? -1 : 1) : null,
      })
    }
  }
  return trades.sort((a, b) => +new Date(b.time) - +new Date(a.time))
}

export function qualityOf(trades: JournalTrade[]): Quality {
  let value = 0
  let covered = 0
  let weighted = 0
  for (const trade of trades) {
    value += trade.value ?? 0
    if (trade.slippageBps != null && trade.value != null && trade.value > 0) {
      covered += trade.value
      weighted += trade.value * trade.slippageBps
    }
  }
  return { value, nTrades: trades.length, slippage: covered > 0 ? weighted / covered : null,
    coverage: value > 0 ? covered / value : 0, amountComplete: trades.every((t) => t.value != null) }
}

/** 每次执行独占一行；复用现有状态归因，但不沿用近期摘要的连续折叠。 */
export function journalExecutions(activity: AccountActivity[]): JournalExecution[] {
  return activity.map((a) => {
    const recent = buildRecentActivity([a], { fetchLimit: 2 }).rows[0]
    const record = a.kind === 'execution' ? a.record : null
    const trades = parseTrades(a)
    const noop = record?.raw_result.status === 'NOOP'
    const status = noop ? '无成交' : recent.type === 'fill' ? '已完成' : recent.type === 'partial' ? '部分到位'
      : recent.type === 'fail' ? '失败' : recent.type === 'terminated' ? '已终止'
        : recent.type === 'blocked' || recent.type === 'skip' ? '已跳过' : trades.length ? '已完成' : '无成交'
    const symbols = record ? [...new Set([
      ...Object.keys(dict(record.raw_result.symbol_results)),
      ...Object.keys(record.raw_input.curr_target ?? {}), ...Object.keys(record.raw_input.last_target ?? {}),
    ])] : []
    return {
      key: a.kind === 'execution' ? `execution:${record?.id ?? record?.execution_id}` : `skip:${a.id}`,
      time: a.occurred_at, executionId: record?.execution_id ?? null, status,
      warning: recent.type === 'partial' || recent.type === 'fail',
      description: noop && record?.raw_result.execution_kind === 'clear_positions' ? '清仓执行 · 无需下单'
        : recent.type === 'noop' && trades.length ? `调仓执行 · ${symbols.length} 个品种` : recentRowText(recent),
      symbols, trades,
    }
  })
}

export function journalSymbols(executions: JournalExecution[], keyword: string): JournalSymbol[] {
  const groups = new Map<string, JournalTrade[]>()
  for (const execution of executions) for (const trade of execution.trades) {
    if (!trade.symbol.toLowerCase().includes(keyword.trim().toLowerCase())) continue
    const group = groups.get(trade.symbol) ?? []
    group.push(trade)
    groups.set(trade.symbol, group)
  }
  return [...groups].map(([symbol, trades]) => {
    trades.sort((a, b) => +new Date(b.time) - +new Date(a.time))
    return { symbol, trades, lastTime: trades[0].time, ...qualityOf(trades) }
  })
}

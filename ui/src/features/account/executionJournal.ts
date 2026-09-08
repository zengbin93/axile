import type { AccountActivity } from '@/lib/api/accounts'
import { buildRecentActivity, recentRowText } from '@/features/account/recent'
import { dict, number } from '@/features/account/executionValues'
import { costTrades, summarizeCosts, shanghaiTime, type CostTrade, type CostSummary } from '@/features/history/costs'
export { loadJournal, type TimeWindow } from '@/features/account/journalActivity'
export { dict, number, sideOf } from '@/features/account/executionValues'

export type JournalRange = '7' | '30' | '90' | 'custom'
export interface JournalTrade extends CostTrade { key: string; executionId: string | null; slippageBps: number | null }
export interface Quality { value: number; nTrades: number; slippage: number | null; coverage: number; amountComplete: boolean }
export interface JournalExecution {
  key: string; recordId: number | null; time: string; executionId: string | null
  status: string; warning: boolean; description: string; symbols: string[]
  trades: JournalTrade[]; summary: CostSummary; durationSec: number | null
}
export interface JournalSymbol extends Quality { symbol: string; lastTime: number; trades: JournalTrade[]; summary: CostSummary }
export const journalAmount = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
export const journalTime = (value: string) => value.replace('T', ' ').slice(0, 16)
export const journalTrade = (trade: CostTrade, key: string): JournalTrade => ({ ...trade, key, executionId: trade.execution_id ?? null, slippageBps: trade.lossBp })
export function qualityOf(trades: JournalTrade[]): Quality {
  const s = summarizeCosts(trades)
  return { value: s.value ?? 0, nTrades: s.count, slippage: s.lossBp, coverage: s.coverage ?? 0, amountComplete: s.amountComplete }
}

/** 日历筛选固定上海时区，结束日包含全天。 */
export function journalWindow(range: JournalRange, from: string, to: string, now = new Date()) {
  const today = new Date(+now + 8 * 3600000).toISOString().slice(0, 10)
  const first = range === 'custom' ? from : today
  const last = range === 'custom' ? to : today
  const valid = (day: string) => /^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(shanghaiTime(`${day}T00:00:00`)) && new Date(shanghaiTime(`${day}T00:00:00`) + 8 * 3600000).toISOString().slice(0, 10) === day
  if (!valid(first) || !valid(last)) return null
  const start = shanghaiTime(`${first}T00:00:00`) - (range === 'custom' ? 0 : (Number(range) - 1) * 86400000)
  const end = shanghaiTime(`${last}T00:00:00`) + 86400000
  return start < end ? { start, end } : null
}

/** 每次执行独占一行；复用现有状态归因，但不沿用近期摘要的连续折叠。 */
export function journalExecutions(activity: AccountActivity[]): JournalExecution[] {
  return activity.map((a) => {
    const recent = buildRecentActivity([a], { fetchLimit: 2 }).rows[0]
    const record = a.kind === 'execution' ? a.record : null
    const trades = record ? costTrades(record).map((t, i) => journalTrade(t, `${record.id ?? record.execution_id}:${i}`)) : []
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
      symbols, trades, summary: summarizeCosts(trades), recordId: record?.id ?? null, durationSec: number(record?.raw_result.execution_time),
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
    trades.sort((a, b) => b.time - a.time)
    return { symbol, trades, lastTime: trades[0].time, summary: summarizeCosts(trades), ...qualityOf(trades) }
  })
}

import { expect, test } from 'bun:test'
import { parseJournalScope, performanceJournalPath, loadCostGroups, compareJournal, snapshotExecution, filterLiveExecutions, journalTotals } from '@/features/account/journalSource'
import { summarizeCosts, combineCosts, costTrades } from '@/features/history/costs'
import { journalExecutions } from '@/features/account/executionJournal'
import type { CostPage } from '@/lib/api/performance'
import type { ExecuteRecord } from '@/types/api'

const record: ExecuteRecord = { id: 5, execution_id: 'e5', created_at: '2026-09-07T17:00:00', is_success: 1, raw_input: {}, raw_result: { symbol_results: {
  A: { sizing: { unit_multiplier: 10 }, first_tick: { bid_price: 99, ask_price: 101 }, orders: [{ order_id: '1', direction: 'buy' }], trades: [{ order_id: '1', trade_price: 101, trade_volume: 2 }] },
  B: { sizing: { unit_multiplier: 10 }, first_tick: { last_price: 100 }, trades: [{ trade_price: 99, trade_volume: 1, extra: { direction: 'sell' } }, { trade_price: 99, trade_volume: 1 }] },
  C: { trades: [{ trade_price: 10, trade_volume: 1 }] },
} } }

test('chart interval link round-trips exact milliseconds without expanding to a calendar day', () => {
  const selection = { kind: 'interval' as const, start: 1788752400001, end: 1788752442003 }
  const url = performanceJournalPath(2, 'snapshot-1', '90', selection)
  const { scope, error } = parseJournalScope(new URL(url, 'http://localhost').searchParams)
  expect(error).toBeNull()
  expect(scope).toEqual({ snapshot_id: 'snapshot-1', range: '90', start: selection.start, end: selection.end })
  expect(parseJournalScope(new URL(performanceJournalPath(2, 's', 'all', { kind: 'execution', recordId: 5, time: 100 }), 'http://localhost').searchParams).scope?.record_id).toBe(5)
})

test('invalid or mixed snapshot filters never fall back to live activity', () => {
  for (const suffix of ['start=1', 'start=2&end=1', 'start=NaN&end=3', 'start=1&end=2&day=2026-09-07', 'day=2026-02-30', 'record_id=0', 'record_id=1&day=2026-09-07', 'start=&end=2']) {
    expect(parseJournalScope(new URLSearchParams(`snapshot_id=s&performance_range=all&${suffix}`)).error).not.toBeNull()
  }
  expect(parseJournalScope(new URLSearchParams('start=1&end=2')).error).not.toBeNull()
  expect(parseJournalScope(new URLSearchParams('range=30')).scope).toBeNull()
})

test('journal and performance agree including incomplete amounts and known direction coverage', () => {
  const rows = journalExecutions([{ kind: 'execution', occurred_at: record.created_at, record }])
  expect(rows[0].summary).toEqual(summarizeCosts(costTrades(record)))
  const perSymbol = ['A', 'B', 'C'].map(symbol => summarizeCosts(rows[0].trades.filter(t => t.symbol === symbol)))
  expect(combineCosts(perSymbol)).toEqual(rows[0].summary)
  expect(journalTotals(filterLiveExecutions(rows, 'b'))).toEqual(perSymbol[1])
  expect(rows[0].summary.amountComplete).toBe(false)
  expect(rows[0].summary.cost).toBe(30)
})

test('cost sorting puts unknown last, improvements after losses and ties in stable order', () => {
  const empty = summarizeCosts([])
  const rows = [{ key: 'unknown', summary: empty }, { key: 'better', summary: { ...empty, cost: -1 } }, { key: 'worse', summary: { ...empty, cost: 2 } }]
  expect(rows.toSorted((a, b) => compareJournal(a, b, 'cost')).map(r => r.key)).toEqual(['worse', 'better', 'unknown'])
})

test('lightweight pagination completes beyond one page and fails closed on broken cursors', async () => {
  const base: CostPage<number> = { snapshot_id: 's', count: 3, summary: { ...summarizeCosts([]), estimated: 0 }, successful: 0, noop: 0, data: [], next_cursor: null }
  const query = { snapshot_id: 's', range: 'all' as const, dimension: 'execution' as const }
  const signal = new AbortController().signal
  const page = await loadCostGroups(2, query, signal, async q => q.cursor ? { ...base, data: [3] } : { ...base, data: [1, 2], next_cursor: 'next' })
  expect(page.data).toEqual([1, 2, 3])
  await expect(loadCostGroups(2, query, signal, async () => ({ ...base, data: [1], next_cursor: 'repeat' }))).rejects.toThrow('分页发生重叠')
  await expect(loadCostGroups(2, query, signal, async () => ({ ...base, data: [1] }))).rejects.toThrow('分页不完整')
  await expect(loadCostGroups(2, query, signal, async () => ({ ...base, snapshot_id: 'new' }))).rejects.toThrow('范围发生变化')
  await expect(loadCostGroups(2, query, signal, async q => { if (q.cursor) throw new Error('offline'); return { ...base, data: [1], next_cursor: 'next' } })).rejects.toThrow('offline')
})

test('snapshot execution status preserves blocked and partial outcomes before is_success', () => {
  const base = { key: '1', record: { id: 1, execution_id: 'e1', created_at: record.created_at, is_success: 0, raw_result: { status: 'BLOCKED' } }, noop: false, symbolCount: 0, summary: summarizeCosts([]) }
  expect(snapshotExecution(base).status).toBe('已跳过')
  expect(snapshotExecution({ ...base, record: { ...base.record, raw_result: { status: 'PARTIAL' } } }).status).toBe('部分到位')
})

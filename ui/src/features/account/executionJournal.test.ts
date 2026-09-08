import { describe, expect, it } from 'bun:test'
import { journalExecutions, journalSymbols, journalWindow, loadJournal, qualityOf } from '@/features/account/executionJournal'
import type { AccountActivity } from '@/lib/api/accounts'

function execution(id: number, result: Record<string, unknown> = {}): AccountActivity {
  return { kind: 'execution', occurred_at: '2026-09-07T10:00:00', record: {
    id, execution_id: `exec-${id}`, created_at: '2026-09-07T10:00:00', is_success: 1,
    raw_input: {}, raw_result: result,
  } }
}
function symbol(price = 99, value: number | null = 1000, tick = true, direction = 'BUY') {
  return { status: 'SUCCEEDED', sizing: value == null ? {} : { unit_multiplier: value / price }, first_tick: tick ? { bid_price: 99, ask_price: 101 } : {},
    orders: [{ order_id: 'order', direction }],
    trades: [{ trade_price: price, trade_volume: 1, trade_value: value, order_id: 'order' }],
  }
}
const window = journalWindow('custom', '2026-09-01', '2026-09-07')!

describe('journal pagination', () => {
  it('loads beyond 500 records without folding individual executions', async () => {
    const data = Array.from({ length: 503 }, (_, i) => execution(i))
    const offsets: number[] = []
    const loaded = await loadJournal(1, window, new AbortController().signal, async (skip) => {
      offsets.push(skip)
      return { data: data.slice(skip, skip + 500), count: data.length }
    })
    expect(offsets).toEqual([0, 500])
    expect(journalExecutions(loaded)).toHaveLength(503)
  })
  it('does not publish partial results when a subsequent page fails', async () => {
    await expect(loadJournal(1, window, new AbortController().signal, async (skip) => {
      if (skip) throw new Error('offline')
      return { data: [execution(1)], count: 2 }
    })).rejects.toThrow('offline')
  })
  it('rejects shifting pagination and duplicate records', async () => {
    await expect(loadJournal(1, window, new AbortController().signal, async (skip) => ({ data: [execution(skip)], count: skip ? 3 : 2 }))).rejects.toThrow('发生变化')
    await expect(loadJournal(1, window, new AbortController().signal, async () => ({ data: [execution(1)], count: 2 }))).rejects.toThrow('重叠')
  })
  it('stops at the lower bound and excludes the day after the end', async () => {
    const a = execution(1)
    const loaded = await loadJournal(1, window, new AbortController().signal, async () => ({
      data: [{ ...a, occurred_at: '2026-09-08T00:00:00' }, { ...execution(2), occurred_at: '2026-09-07T23:59:59' }, { ...execution(3), occurred_at: '2026-08-31T23:59:59' }], count: 100,
    }))
    expect(loaded).toHaveLength(1)
  })
})

describe('journal quality', () => {
  it('weights loss by projected notional and reports partial coverage', () => {
    const rows = journalExecutions([execution(1, { symbol_results: { A: symbol(99, 9000), B: symbol(101, 1000), C: symbol(100, 10000, false) } })])
    const q = qualityOf(rows[0].trades)
    expect(q.slippage).toBeCloseTo(-80)
    expect(q.coverage).toBe(0.5)
    expect(q.value).toBe(20000)
    expect(journalSymbols(rows, 'b').map((s) => s.symbol)).toEqual(['B'])
  })
  it('does not invent direction or futures notional for missing fields', () => {
    const rows = journalExecutions([execution(1, { symbol_results: { A: symbol(99, null), B: symbol(99, 1000, true, '') } })])
    const q = qualityOf(rows[0].trades)
    expect(q.amountComplete).toBe(false)
    expect(q.slippage).toBeNull()
    expect(rows[0].trades[1].slippageBps).toBeNull()
  })
  it('keeps failed, terminated, noop and schedule skip rows individually with detail identities', () => {
    const rows = journalExecutions([
      execution(1), execution(2, { task_status: 'TERMINATED' }),
      { ...execution(3), kind: 'execution', record: { ...(execution(3) as Extract<AccountActivity, { kind: 'execution' }>).record, is_success: 0 } },
      { kind: 'schedule_skip', id: 5, occurred_at: '2026-09-07T10:00:00', channel: 'tq', reason_code: 'CALENDAR.CLOSED', calendar_day: '2026-09-07', calendar_id: '', calendar_label: '' },
    ])
    expect(rows.map((r) => r.status)).toEqual(['无成交', '已终止', '失败', '已跳过'])
    expect(rows[0].executionId).toBe('exec-1')
    expect(rows[3].executionId).toBeNull()
  })
  it('retains equal-time equal-value trades as separate rows', () => {
    const s = symbol()
    const rows = journalExecutions([execution(1, { symbol_results: { A: { ...s, trades: [...s.trades, ...s.trades] } } })])
    expect(new Set(rows[0].trades.map((t) => t.key)).size).toBe(2)
  })
  it('does not label a NOOP clear as a completed fill', () => {
    const row = journalExecutions([execution(1, { status: 'NOOP', execution_kind: 'clear_positions' })])[0]
    expect(row.status).toBe('无成交')
    expect(row.description).toBe('清仓执行 · 无需下单')
  })
})

it('uses today for relative ranges and rejects reversed custom dates', () => {
  const w = journalWindow('7', '', '', new Date('2026-09-07T12:00:00'))!
  expect(new Date(w.start).toISOString()).toBe('2026-08-31T16:00:00.000Z')
  expect(new Date(w.end).toISOString()).toBe('2026-09-07T16:00:00.000Z')
  expect(journalWindow('custom', '2026-09-08', '2026-09-07')).toBeNull()
})

it('retains malformed fills as unknown and rejects overflow calendar dates', () => {
  const row = journalExecutions([execution(1, { symbol_results: { A: { ...symbol(), trades: [{ trade_volume: 1 }] } } })])[0]
  expect(row.trades).toHaveLength(1)
  expect(row.summary.count).toBe(1)
  expect(row.summary.cost).toBeNull()
  expect(row.summary.amountComplete).toBe(false)
  expect(journalWindow('custom', '2026-02-30', '2026-03-01')).toBeNull()
})

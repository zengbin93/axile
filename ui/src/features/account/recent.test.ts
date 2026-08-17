import { expect, test } from 'bun:test'
import { buildRecentRows } from './recent'
import type { ExecuteRecord } from '../../types/api'

/** 造一条执行记录。kind: 'fill' | 'noop' | 'fail'。 */
function rec(id: number, kind: 'fill' | 'noop' | 'fail'): ExecuteRecord {
  const base = {
    id,
    execution_id: `e${id}`,
    created_at: `2026-07-02T10:${String(id % 60).padStart(2, '0')}:00`,
    strategy_config: [],
    raw_result: { account_assets: { total_asset: 1000 } },
  }
  if (kind === 'fail') return { ...base, is_success: 0, raw_input: {} }
  if (kind === 'noop') return { ...base, is_success: 1, raw_input: { curr_target: { BTC: 0.5 }, last_target: { BTC: 0.5 } } }
  return { ...base, is_success: 1, raw_input: { curr_target: { BTC: 0.6 }, last_target: { BTC: 0.5 } } }
}

test('连续空跑折叠成一行并计数', () => {
  const { rows } = buildRecentRows([rec(3, 'noop'), rec(2, 'noop'), rec(1, 'noop')])
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ type: 'noop', count: 3 })
})

test('连续失败折叠成一行并计数', () => {
  const { rows } = buildRecentRows([rec(3, 'fail'), rec(2, 'fail')])
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ type: 'fail', count: 2, executionId: 'e3' })
})

test('成交逐条保留，含变动描述', () => {
  const { rows } = buildRecentRows([rec(1, 'fill')])
  expect(rows[0]).toMatchObject({ type: 'fill', desc: '调仓执行 · 1 处变动' })
})

test('交错时按时间保序、分段折叠', () => {
  const { rows } = buildRecentRows([rec(4, 'fail'), rec(3, 'fail'), rec(2, 'fill'), rec(1, 'noop')])
  expect(rows.map((r) => r.type)).toEqual(['fail', 'fill', 'noop'])
  expect(rows[0]).toMatchObject({ type: 'fail', count: 2 })
})

test('末尾失败组在窗口拉满时标记饱和(N+)', () => {
  const recs = Array.from({ length: 5 }, (_, k) => rec(5 - k, 'fail'))
  const { rows } = buildRecentRows(recs, { fetchLimit: 5 })
  expect(rows[0]).toMatchObject({ type: 'fail', count: 5, saturated: true })
})

test('未拉满窗口不标记饱和', () => {
  const recs = Array.from({ length: 3 }, (_, k) => rec(3 - k, 'fail'))
  const { rows } = buildRecentRows(recs, { fetchLimit: 50 })
  expect(rows[0]).toMatchObject({ saturated: false })
})

test('限量到 cap 并标记 truncated', () => {
  const recs = Array.from({ length: 10 }, (_, k) => rec(10 - k, 'fill'))
  const { rows, truncated } = buildRecentRows(recs, { cap: 6 })
  expect(rows).toHaveLength(6)
  expect(truncated).toBe(true)
})

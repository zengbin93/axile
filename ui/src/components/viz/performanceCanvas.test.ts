import { expect, test } from 'bun:test'
import { executionMarkerTone } from '@/components/viz/performanceCanvas'
import type { CostExecutionRow } from '@/lib/api/performance'

const summary = { value: 100, cost: 1, lossBp: 100, coverage: 1, covered: 1, count: 1, amountComplete: true, fees: {}, feeCovered: 0 }
const record = (success = 1) => ({ id: 1, execution_id: 'exec-1', created_at: '1970-01-01T00:00:00Z', is_success: success, raw_result: {} })
const row = (over: Partial<CostExecutionRow> = {}): CostExecutionRow => ({ key: '1', record: record(), summary, noop: false, symbolCount: 1, transactions: [], positions: [], ...over })

test('失败或成交覆盖不全走琥珀，其余一律中性', () => {
  expect(executionMarkerTone(row())).toBe('normal')
  expect(executionMarkerTone(row({ record: record(0) }))).toBe('warn')
  expect(executionMarkerTone(row({ summary: { ...summary, coverage: 0.5, covered: 1, count: 2 } }))).toBe('warn')
  expect(executionMarkerTone(row({ summary: { ...summary, coverage: null } }))).toBe('warn')
})

test('空跑与有利成交不再单独着色——质量细节由成本面板承载', () => {
  expect(executionMarkerTone(row({ noop: true, transactions: [], symbolCount: 0 }))).toBe('normal')
  expect(executionMarkerTone(row({ summary: { ...summary, lossBp: -20 } }))).toBe('normal')
})

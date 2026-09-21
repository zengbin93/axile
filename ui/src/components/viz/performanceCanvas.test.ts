import { expect, test } from 'bun:test'
import { chartAxis, executionMarkerPoint, executionMarkerTone, hasExecutionMarker, returnY, type CanvasTheme, type ChartScene } from '@/components/viz/performanceCanvas'
import { pointTime } from '@/features/history/chartModel'
import { shanghaiTime } from '@/features/history/costs'
import type { AccountPerformance } from '@/types/api'
import type { CostExecutionRow, TransactionPreview } from '@/lib/api/performance'

const summary = { value: 100, cost: 1, lossBp: 100, coverage: 1, covered: 1, count: 1, amountComplete: true, fees: {}, feeCovered: 0 }
const record = (success = 1) => ({ id: 1, execution_id: 'exec-1', created_at: '1970-01-01T00:00:00Z', is_success: success, raw_result: {} })
const trade = (time = 0): TransactionPreview => ({ symbol: 'A', side: 'buy', quantity: 1, price: 100, reference: 99, referenceSource: 'mid', time, endTime: time, timeEstimated: false, before: 0, target: 1, summary })
const row = (over: Partial<CostExecutionRow> = {}): CostExecutionRow => ({ key: '1', record: record(), summary, noop: false, symbolCount: 1, transactions: [trade()], positions: [], ...over })

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

test('无成交不画点（失败的也一样），有真实成交保留', () => {
  expect(hasExecutionMarker(row({ noop: true, transactions: [], symbolCount: 0 }))).toBe(false)
  expect(hasExecutionMarker(row({ noop: true, transactions: [], symbolCount: 0, record: record(0) }))).toBe(false)
  expect(hasExecutionMarker(row())).toBe(true)
})

const theme: CanvasTheme = { bg: '#fff', surface: '#fff', ink: '#000', muted: '#888', line: '#ddd', accent: '#06c', warn: '#fa0', fill: '#eee', font: 'sans-serif' }

function markerScene(returns: number[]): ChartScene {
  const data: AccountPerformance = {
    backtest_included: true,
    settings: { backtest_weight_type: 'cs', backtest_fee_rate: 0 },
    engine_version: 'test',
    range: 'all',
    baseline: null,
    end: null,
    record_count: returns.length,
    observation_count: returns.length,
    used_record_count: returns.length,
    invalid_asset_count: 0,
    skips: null,
    points: returns.map((value, index) => ({
      account_equity: 100,
      date: `2026-01-${String(index + 1).padStart(2, '0')}`,
      record_id: index + 1,
      execution_id: null,
      account_return: value,
      portfolio_return: value,
      account_daily_return: null,
      portfolio_daily_return: null,
      difference: 0,
    })),
    bindings: [],
    calendar: { status: 'not_required', calendar_id: null, label: null, closed_ranges: [], unavailable_ranges: [] },
  }
  const times = data.points.map(pointTime)
  return {
    data, times, width: 900,
    viewport: { start: shanghaiTime('2025-12-31T04:00:00Z'), end: shanghaiTime('2026-01-05T04:00:00Z') },
    daily: false, portfolioNames: new Map(), costs: null, theme,
  }
}

test('区间首尾外侧的执行吸附到最近观测点取值，x 仍按真实时间投影', () => {
  const scene = markerScene([0.05, 0.1, -0.02])
  const axis = chartAxis(scene)
  const first = scene.data.points[0], last = scene.data.points[scene.data.points.length - 1]
  const early = executionMarkerPoint(scene, row({ record: { ...record(), id: 901, created_at: '2025-12-31T04:00:00Z' } }))
  expect(early).not.toBeNull()
  expect(early!.y).toBeCloseTo(returnY(first.account_return!, axis), 10)
  const late = executionMarkerPoint(scene, row({ record: { ...record(), id: 902, created_at: '2026-01-05T04:00:00Z' } }))
  expect(late).not.toBeNull()
  expect(late!.y).toBeCloseTo(returnY(last.account_return!, axis), 10)
})

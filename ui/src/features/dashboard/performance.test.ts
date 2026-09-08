import { expect, test } from 'bun:test'
import { cardPerformance, openFullPerformance } from './performance'
import { performanceViews, performanceViewports } from '@/features/history/viewState'
import { performanceEntry } from '@/features/history/performanceCache'
import { sparklinePath } from '@/components/viz/sparklineGeometry'
import type { PerformanceSummary, PerformancePoint } from '@/types/api'

const summary: PerformanceSummary = {
  snapshot_id: 'one', status: 'ready', computed_at: null, observed_at: '2026-09-07T17:00:00+08:00',
  account_equity: 117128.71, account_daily_return: -0.012, points: [],
}

test('金额和日涨跌来自同一观测，日期按上海时间判断', () => {
  expect(cardPerformance(summary, Date.parse('2026-09-07T15:59:00Z'))).toMatchObject({ equity: 117128.71, pct: -1.2, dayLabel: '今日' })
  expect(cardPerformance(summary, Date.parse('2026-09-07T16:00:00Z')).dayLabel).toBe('2026-09-07')
  expect(cardPerformance().equity).toBeNull()
  expect(cardPerformance({ ...summary, account_equity: null }).equity).toBeNull()
  expect(cardPerformance({ ...summary, status: 'stale' })).toMatchObject({ equity: 117128.71, statusLabel: '绩效更新中' })
  expect(cardPerformance({ ...summary, status: 'failed' })).toMatchObject({ equity: 117128.71, statusLabel: '绩效更新失败' })
})

const point = (day: number, value: number | null): PerformancePoint => ({ date: `2026-01-${String(day).padStart(2, '0')}`, observed_at: `2026-01-${String(day).padStart(2, '0')}T00:00:00+08:00`, account_return: value, portfolio_return: null, account_daily_return: null, portfolio_daily_return: null, difference: null })

test('迷你线按真实时间间隔绘制并保留空值断点', () => {
  const path = sparklinePath([point(1, 0), point(2, .1), point(3, null), point(5, .2), point(6, .3)], 106, 36)
  expect(path).toBe('M3.00,33.00 L23.00,23.00  M83.00,13.00 L103.00,3.00')
  expect(sparklinePath([point(1, 0), point(2, 0)], 106, 36)).toBe('M3.00,18.00 L103.00,18.00')
  expect(sparklinePath([], 106, 36)).toBe('')
})

test('小图入口清除旧区间和缩放，仅预取绩效快照', async () => {
  const original = globalThis.fetch
  const urls: string[] = []
  globalThis.fetch = Object.assign(async (input: RequestInfo | URL) => {
    urls.push(String(input))
    return Response.json({ snapshot_id: null, status: 'empty', result: null })
  }, { preconnect: original.preconnect })
  try {
    performanceViews.set(991, { range: '30', view: 'daily', selection: null })
    performanceViewports.set('991:all', { start: 1, end: 2 })
    openFullPerformance(991)
    await performanceEntry(991, 'all').flight
    expect(performanceViews.get(991)).toEqual({ range: 'all', view: 'cumulative', selection: null })
    expect(performanceViewports.has('991:all')).toBe(false)
    expect(urls).toHaveLength(1)
    expect(urls[0]).toContain('/account/performance/991/snapshot?range=all')
  } finally { globalThis.fetch = original }
})

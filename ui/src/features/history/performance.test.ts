import { expect, test } from 'bun:test'
import { chartTime, returnPaths, returnText, settingsFromDraft, WEIGHT_MODES } from './performance'
import type { PerformancePoint } from '@/types/api'

test('模式使用中文标签，费率从 BP 转为账户小数配置', () => {
  expect(WEIGHT_MODES.map(m => m.label)).toEqual(['时序', '截面'])
  expect(settingsFromDraft('ts', '2')).toEqual({ backtest_weight_type: 'ts', backtest_fee_rate: 0.0002 })
  for (const value of ['', ' ', '-1', '10000', 'NaN', 'Infinity']) expect(settingsFromDraft('ts', value)).toBeNull()
  expect(settingsFromDraft('cs', '0')?.backtest_fee_rate).toBe(0)
})

test('缺失收益断线，真实零收益保留', () => {
  const points = [0, 0.1, null, 0.2].map(v => ({ portfolio_return: v }) as PerformancePoint)
  expect(returnPaths(points, 'portfolio_return', i => i, v => v)).toBe('M0,0 L1,0.1 M3,0.2 ')
  expect(returnText(null)).toBe('—')
  expect(returnText(0)).toBe('0.00%')
  expect(returnText(-0.01, ' 个百分点')).toBe('-1.00 个百分点')
})

test('上海日末收益点晚于当日执行基准', () => {
  expect(chartTime('2026-01-01')).toBeGreaterThan(chartTime('2026-01-01T09:00:00'))
})

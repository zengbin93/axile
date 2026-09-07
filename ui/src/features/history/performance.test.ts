import { expect, test } from 'bun:test'
import { axisPercent, chartTime, feeOption, returnPaths, returnText, settingsFromDraft, timeTicks, WEIGHT_MODES } from './performance'
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

test('费率预设按数值匹配，自定义保留小数和非法输入', () => {
  for (const fee of ['0', '5', '15', '30']) expect(feeOption(fee)).toBe(fee)
  expect(feeOption('5.0')).toBe('5')
  for (const fee of ['', ' ', '2.5', '-1']) expect(feeOption(fee)).toBe('custom')
  expect(settingsFromDraft('ts', '2.5')?.backtest_fee_rate).toBe(0.00025)
})

test('小幅收益刻度保持可区分并消除负零', () => {
  const labels = [0, -0.000325, -0.00065, -0.000975, -0.0013].map(value => axisPercent(value, 0.000325))
  expect(new Set(labels).size).toBe(5)
  expect(axisPercent(-0.00000001, 0.000325)).toBe('0.00%')
})

test('同日基准与日末不重复，过密中间日期被省略', () => {
  const points = ['2026-09-07T10:30:00', '2026-09-07'].map(date => ({ date }) as PerformancePoint)
  expect(timeTicks(points, i => i * 200).map(t => t.label)).toEqual(['10:30', '日末'])
  const days = ['2026-09-07', '2026-09-08', '2026-09-09'].map(date => ({ date }) as PerformancePoint)
  expect(timeTicks(days, i => i * 80).map(t => t.index)).toEqual([0, 2])
})

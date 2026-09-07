import type { PerformancePoint, PerformanceSettings } from '@/types/api'

export const WEIGHT_MODES: Array<{ value: 'ts' | 'cs'; label: string }> = [
  { value: 'ts', label: '时序' }, { value: 'cs', label: '截面' },
]

export function settingsFromDraft(mode: 'ts' | 'cs', feeBp: string): PerformanceSettings | null {
  if (!feeBp.trim()) return null
  const fee = Number(feeBp)
  if (!Number.isFinite(fee) || fee < 0 || fee >= 10000) return null
  return { backtest_weight_type: mode, backtest_fee_rate: fee / 10000 }
}

export function returnText(value: number | null | undefined, unit = '%'): string {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}${unit}`
}

export function chartTime(date: string): number {
  // 日收益点放在上海日末，共同基准保留实际执行时间。
  return new Date(`${date.includes('T') ? date : `${date}T23:59:59`}+08:00`).getTime()
}

export function returnPaths(points: PerformancePoint[], key: keyof PerformancePoint, x: (i: number) => number, y: (v: number) => number): string {
  let path = ''
  let connected = false
  points.forEach((point, i) => {
    const value = point[key]
    if (typeof value !== 'number') { connected = false; return }
    path += `${connected ? 'L' : 'M'}${x(i)},${y(value)} `
    connected = true
  })
  return path
}

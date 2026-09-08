import type { PerformancePoint } from '@/types/api'
import { pointTime } from '@/features/history/chartModel'

/** 与绩效大图共用观测时间和累计收益；缺值断线。 */
export function sparklinePath(data: PerformancePoint[], width: number, height: number): string {
  const valid = data.filter(p => p.account_return != null && Number.isFinite(p.account_return) && Number.isFinite(pointTime(p)))
  if (valid.length < 2) return ''
  const values = valid.map(p => p.account_return!)
  const min = Math.min(...values), max = Math.max(...values)
  const first = pointTime(data[0]), last = pointTime(data[data.length - 1])
  const span = last - first || 1
  const range = max - min || 1
  let connected = false
  return data.map(point => {
    const value = point.account_return, time = pointTime(point)
    if (value == null || !Number.isFinite(value) || !Number.isFinite(time)) { connected = false; return '' }
    const x = 3 + (time - first) / span * (width - 6)
    const y = max === min ? height / 2 : 3 + (max - value) / range * (height - 6)
    const command = connected ? 'L' : 'M'
    connected = true
    return command + x.toFixed(2) + ',' + y.toFixed(2)
  }).join(' ')
}

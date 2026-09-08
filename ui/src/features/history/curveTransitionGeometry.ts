import { chartAxis, returnY, xPosition, type ChartScene } from '@/components/viz/performanceCanvas'
import type { CurvePoint } from '@/components/viz/sparklineGeometry'
import { pointTime } from '@/features/history/chartModel'
import type { PerformancePoint } from '@/types/api'

/** CSS 压缩会把 360ms 改写为 .36s；不能直接 parseFloat 后当毫秒。 */
export function curveDurationMs(value: string, fallback: number): number {
  const match = value.trim().match(/^(\d*\.?\d+)(ms|s)$/)
  const duration = match ? Number(match[1]) * (match[2] === 's' ? 1000 : 1) : NaN
  return Number.isFinite(duration) && duration > 0 ? duration : fallback
}

/** 使用真实 Canvas 坐标；不跨缺值，也不更改时间间隔。 */
export function performanceCoordinates(scene: ChartScene, points: PerformancePoint[] = scene.data.points): CurvePoint[] {
  const axis = chartAxis(scene)
  return points.map(point => {
    const time = pointTime(point), value = point.account_return
    return value == null || !Number.isFinite(value) || !Number.isFinite(time)
      ? null
      : { x: xPosition(time, scene.width, scene.viewport), y: returnY(value, axis) }
  })
}

export function translateCurve(points: CurvePoint[], left: number, top: number): CurvePoint[] {
  return points.map(point => point && ({ x: point.x + left, y: point.y + top }))
}

export function interpolateCurve(from: CurvePoint[], to: CurvePoint[], progress: number): CurvePoint[] {
  return from.map((point, i) => {
    const end = to[i]
    return point && end ? { x: point.x + (end.x - point.x) * progress, y: point.y + (end.y - point.y) * progress } : null
  })
}

/** 快照不同只做空间展开；数据版本变化留到终点交接，不伪造逐点对应关系。 */
export function fitCurve(from: CurvePoint[], target: CurvePoint[]): CurvePoint[] {
  const sourcePoints = from.filter(point => point != null)
  const targetPoints = target.filter(point => point != null)
  if (!sourcePoints.length || !targetPoints.length) return []
  const bounds = (points: NonNullable<CurvePoint>[]) => ({
    left: Math.min(...points.map(p => p.x)), right: Math.max(...points.map(p => p.x)),
    top: Math.min(...points.map(p => p.y)), bottom: Math.max(...points.map(p => p.y)),
  })
  const source = bounds(sourcePoints), destination = bounds(targetPoints)
  return from.map(point => point && ({
    x: destination.left + (point.x - source.left) / (source.right - source.left || 1) * (destination.right - destination.left),
    y: source.bottom === source.top ? (destination.top + destination.bottom) / 2
      : destination.top + (point.y - source.top) / (source.bottom - source.top) * (destination.bottom - destination.top),
  }))
}

import type { PerformancePoint } from '@/types/api'
import { sparklinePath } from './sparklineGeometry'

export function Sparkline({ data, width = 96, height = 30 }: { data: PerformancePoint[]; width?: number; height?: number }) {
  return <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block" role="img" aria-label="全部区间累计收益">
    <title>全部区间累计收益</title>
    <path d={sparklinePath(data, width, height)} fill="none" stroke="var(--color-accent)" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

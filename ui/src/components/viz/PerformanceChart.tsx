import { useLayoutEffect, useRef, useState, type PointerEvent } from 'react'
import type { AccountPerformance, PerformancePoint } from '@/types/api'
import { chartTime, returnPaths } from '@/features/history/performance'

const HEIGHT = 300
const LEFT = 65
const RIGHT = 20
const TOP = 24
const BOTTOM = 32

export function PerformanceChart({ data, daily, hoverIndex, onHover }: {
  data: AccountPerformance
  daily: boolean
  hoverIndex: number | null
  onHover: (index: number | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(900)
  useLayoutEffect(() => {
    const element = container.current
    if (!element) return
    const measure = () => setWidth(Math.max(280, element.clientWidth))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const points = data.points
  const WIDTH = width
  const keys: Array<keyof PerformancePoint> = daily ? ['account_daily_return', 'portfolio_daily_return'] : ['account_return', 'portfolio_return']
  const colors = ['var(--color-accent)', 'var(--color-ink-2)']
  const values = points.flatMap(p => keys.map(k => p[k]).filter((v): v is number => typeof v === 'number'))
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const span = max - min || 0.01
  const times = points.map(p => chartTime(p.date))
  const first = times[0]
  const last = times[times.length - 1]
  const XTime = (t: number) => LEFT + (t - first) / (last - first || 1) * (WIDTH - LEFT - RIGHT)
  const X = (i: number) => XTime(times[i])
  const Y = (v: number) => TOP + (max - v) / span * (HEIGHT - TOP - BOTTOM)
  const move = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = (event.clientX - rect.left) / rect.width * WIDTH
    onHover(times.reduce((best, _, i) => Math.abs(X(i) - x) < Math.abs(X(best) - x) ? i : best, 0))
  }
  const barWidth = Math.min(12, (WIDTH - LEFT - RIGHT) / points.length / 3)
  return <div ref={container}>
    {data.observation_count < 2 || points.length < 2 ? <div className="flex h-[280px] items-center justify-center text-sm text-ink-3">有效观测不足两条</div> :
    <svg data-testid="performance-chart" role="img" aria-label={daily ? '每日收益对比' : '累计收益对比'} tabIndex={0}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-[300px] w-full outline-none"
      onPointerMove={move} onPointerLeave={() => onHover(null)} onBlur={() => onHover(null)}
      onKeyDown={event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          onHover(Math.max(0, Math.min(points.length - 1, (hoverIndex ?? points.length - 1) + (event.key === 'ArrowLeft' ? -1 : 1))))
        }
      }}>
      {[0, 0.25, 0.5, 0.75, 1].map(f => {
        const value = min + span * f
        return <g key={f}><line x1={LEFT} x2={WIDTH - RIGHT} y1={Y(value)} y2={Y(value)} stroke="var(--color-line)" />
          <text x={LEFT - 8} y={Y(value) + 4} textAnchor="end" fontSize={12} fill="var(--color-ink-3)">{(value * 100).toFixed(1)}%</text></g>
      })}
      {data.bindings.map((binding, i) => <g key={i}><title>{binding.time} · {binding.portfolio_id == null ? '解绑' : `组合 #${binding.portfolio_id}`}</title>
        <line x1={XTime(chartTime(binding.time))} x2={XTime(chartTime(binding.time))} y1={TOP} y2={HEIGHT - BOTTOM} stroke="var(--color-ink-3)" strokeDasharray="3 5" />
      </g>)}
      {keys.map((key, series) => daily ? <g key={key}>{points.map((point, i) => {
        const value = point[key]
        return typeof value === 'number' ? <rect key={i} x={X(i) + (series - 1) * barWidth} y={Math.min(Y(0), Y(value))}
          width={barWidth} height={Math.max(0.5, Math.abs(Y(value) - Y(0)))} fill={colors[series]} opacity={0.8} /> : null
      })}</g> : <path key={key} data-series={key} d={returnPaths(points, key, X, Y)} fill="none" stroke={colors[series]} strokeWidth={2} />)}
      {[0, Math.floor((points.length - 1) / 2), points.length - 1].map((i, label) => <text key={label} x={X(i)} y={HEIGHT - 8} textAnchor={label === 0 ? 'start' : label === 2 ? 'end' : 'middle'} fontSize={12} fill="var(--color-ink-3)">{points[i].date.slice(0, 10)}</text>)}
      {hoverIndex != null && points[hoverIndex] && <line x1={X(hoverIndex)} x2={X(hoverIndex)} y1={TOP} y2={HEIGHT - BOTTOM} stroke="var(--color-ink-3)" strokeDasharray="4 3" />}
    </svg>}
  </div>
}

/**
 * 权益走势迷你线（纯 SVG，无图表库）。
 *
 * 配色口径：曲线是**连续轨迹**、非离散 Δ，故走中性 `--color-accent`，不按涨跌上红绿。
 * 按 theme.css 铁律，红/绿只留给**离散**的涨跌/盈亏数字（今日%、区间盈亏），曲线保持中性；
 * 这也与绩效页 `EquityChart` 同色，页间色相连续（曲线本身不挂共享元素）。
 */

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
}

/**
 * 量程相对下限：波动小于「均值 × 此比例」时视为基本没动，按此下限铺量程，避免
 * min/max 自动缩放把 0.0x% 的噪声吹成占满全高的假悬崖。真有 ≥1% 波动照常铺满。
 */
const MIN_REL_RANGE = 0.01

export function Sparkline({ data, width = 96, height = 30 }: SparklineProps) {
  const pts = data.filter((v) => Number.isFinite(v))
  if (pts.length < 2) return <svg width={width} height={height} />

  const pad = 3
  const min = Math.min(...pts)
  const max = Math.max(...pts)
  // 居中画：以中值为轴，量程取「真实极差」与「均值 × 相对下限」的较大者。变动够大时
  // 极差主导、照旧铺满上下；近乎持平时下限兜底，线趋近平，不再假跳崖。
  const mid = (min + max) / 2
  const rng = Math.max(max - min, Math.abs(mid) * MIN_REL_RANGE) || 1
  const path = pts
    .map((v, i) => {
      const x = pad + (i * (width - 2 * pad)) / (pts.length - 1)
      const y = pad + (height - 2 * pad) * (0.5 - (v - mid) / rng)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block">
      <polyline
        points={path}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

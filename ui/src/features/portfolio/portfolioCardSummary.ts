import type { TargetWeightSnapshot } from '@/types/api'

const ACTIVE_WEIGHT_EPSILON = 1e-9

export interface PortfolioTargetEntry {
  symbol: string
  weight: number
}

export interface PortfolioTargetSummary {
  activeCount: number
  grossExposure: number
  netExposure: number
  topEntries: PortfolioTargetEntry[]
  hiddenCount: number
}

export type PortfolioTargetState =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'uncalculated' }
  | { kind: 'empty'; calculatedAt: string; stale: boolean }
  | { kind: 'ready'; calculatedAt: string; stale: boolean; summary: PortfolioTargetSummary }

/** 将只读目标快照整理成组合卡片需要的稳定摘要。 */
export function portfolioTargetSummary(
  snapshot: TargetWeightSnapshot,
  visibleLimit = 4,
): PortfolioTargetSummary {
  const entries = Object.entries(snapshot.weights)
    .filter(([, weight]) => Math.abs(weight) > ACTIVE_WEIGHT_EPSILON)
    .sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]))

  return {
    activeCount: entries.length,
    grossExposure: entries.reduce((sum, [, weight]) => sum + Math.abs(weight), 0),
    netExposure: entries.reduce((sum, [, weight]) => sum + weight, 0),
    topEntries: entries.slice(0, visibleLimit).map(([symbol, weight]) => ({ symbol, weight })),
    hiddenCount: Math.max(0, entries.length - visibleLimit),
  }
}

/** 区分加载失败、从未计算、目标为空和已有目标，避免把缺数据画成健康空仓。 */
export function portfolioTargetState(
  snapshot: TargetWeightSnapshot | null,
  loading: boolean,
  error: Error | null,
  stale: boolean,
): PortfolioTargetState {
  if (!snapshot) {
    if (loading) return { kind: 'loading' }
    if (error) return { kind: 'unavailable' }
    return { kind: 'uncalculated' }
  }
  if (!snapshot.calculated_at) return { kind: 'uncalculated' }

  const summary = portfolioTargetSummary(snapshot)
  if (summary.activeCount === 0) {
    return { kind: 'empty', calculatedAt: snapshot.calculated_at, stale }
  }
  return { kind: 'ready', calculatedAt: snapshot.calculated_at, stale, summary }
}

export function formatTargetWeight(weight: number, signed = true): string {
  const percentage = Number((weight * 100).toFixed(1))
  const prefix = signed && percentage > 0 ? '+' : ''
  return `${prefix}${percentage.toFixed(1)}%`
}

/** 以北京时间显示卡片所需的紧凑自然日期。 */
export function formatTargetUpdatedAt(iso: string, now = Date.now()): string {
  const withZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}+08:00`
  const target = new Date(withZone)
  const current = new Date(now)
  if (Number.isNaN(target.getTime())) return '—'

  const parts = (date: Date) => {
    const values = Object.fromEntries(
      new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      })
        .formatToParts(date)
        .filter((part) => part.type !== 'literal')
        .map((part) => [part.type, Number(part.value)]),
    )
    return values as Record<'year' | 'month' | 'day' | 'hour' | 'minute', number>
  }
  const targetParts = parts(target)
  const currentParts = parts(current)
  const day = (value: typeof targetParts) => Date.UTC(value.year, value.month - 1, value.day) / 86_400_000
  const difference = day(currentParts) - day(targetParts)
  const time = `${String(targetParts.hour).padStart(2, '0')}:${String(targetParts.minute).padStart(2, '0')}`
  if (difference === 0) return `今天 ${time}`
  if (difference === 1) return `昨天 ${time}`
  const year = targetParts.year === currentParts.year ? '' : `${targetParts.year} 年 `
  return `${year}${targetParts.month} 月 ${targetParts.day} 日 ${time}`
}

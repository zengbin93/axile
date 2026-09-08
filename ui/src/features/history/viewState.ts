import type { ChartSelection, Viewport } from '@/features/history/chartModel'
import type { PerformanceRange } from '@/lib/api/performance'

export const performanceViews = new Map<number, { range: PerformanceRange; view: 'cumulative' | 'daily'; selection: ChartSelection; scroll?: number }>()
export const performanceViewports = new Map<string, Viewport>()

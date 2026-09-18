import type { ChartSelection, Viewport } from '@/features/history/chartModel'
import type { PerformanceRange } from '@/lib/api/performance'
import type { TimeScaleMode } from '@/features/history/timeScale'

export const performanceViews = new Map<number, { range: PerformanceRange; view: 'cumulative' | 'daily'; scale?: TimeScaleMode; selection: ChartSelection; scroll?: number }>()
export const performanceViewports = new Map<string, Viewport>()

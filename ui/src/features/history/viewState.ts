import type { ChartSelection, Viewport } from '@/features/history/chartModel'
import type { PerformanceRange } from '@/lib/api/performance'
import type { TimeScaleMode } from '@/features/history/timeScale'

export type BacktestMode = 'sized' | 'target'
export const performanceViews = new Map<number, { range: PerformanceRange; view: 'cumulative' | 'daily'; scale?: TimeScaleMode; selection: ChartSelection; scroll?: number; markers?: boolean; backtestMode?: BacktestMode }>()
export const performanceViewports = new Map<string, Viewport>()

export interface PerformanceViewPrefs {
  scale: TimeScaleMode
  markers: boolean
  backtestMode: BacktestMode
}

const prefKey = (accountId: number) => `axon.performance-view:${accountId}`
const SCALES: TimeScaleMode[] = ['observations', 'natural']

/** 读取按账户持久化的尺度/成交点偏好；损坏或缺失时回退空对象。 */
export function loadPerformanceView(accountId: number): Partial<PerformanceViewPrefs> {
  try {
    const raw = localStorage.getItem(prefKey(accountId))
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Partial<PerformanceViewPrefs>
    return {
      scale: SCALES.includes(parsed.scale as TimeScaleMode) ? (parsed.scale as TimeScaleMode) : undefined,
      markers: typeof parsed.markers === 'boolean' ? parsed.markers : undefined,
      backtestMode: parsed.backtestMode === 'target' ? 'target' : 'sized',
    }
  } catch {
    return {}
  }
}

/** 把尺度/成交点偏好写入 localStorage；写入失败（隐私模式/配额）静默忽略。 */
export function savePerformanceView(accountId: number, prefs: PerformanceViewPrefs): void {
  try {
    localStorage.setItem(prefKey(accountId), JSON.stringify(prefs))
  } catch {
    // 持久化是增强而非依赖，失败时仅丢失跨会话记忆。
  }
}

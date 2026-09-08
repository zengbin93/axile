import type { PerformanceSummary } from '@/types/api'
import { shanghaiDay } from '@/features/history/costs'
import { performanceViews, performanceViewports } from '@/features/history/viewState'
import { checkPerformance } from '@/features/history/performanceCache'

export function cardPerformance(summary?: PerformanceSummary, now = Date.now()) {
  const day = summary?.observed_at ? shanghaiDay(summary.observed_at) : null
  return {
    equity: summary?.account_equity ?? null,
    pct: summary?.account_daily_return == null ? null : summary.account_daily_return * 100,
    dayLabel: day == null ? '日涨跌' : day === shanghaiDay(new Date(now).toISOString()) ? '今日' : day,
    statusLabel: !summary || summary.status === 'empty' ? '暂无绩效' : summary.status === 'failed' ? '绩效更新失败' : summary.status === 'pending' || summary.status === 'stale' ? '绩效更新中' : '',
  }
}

export function openFullPerformance(accountId: number) {
  performanceViews.set(accountId, { range: 'all', view: 'cumulative', selection: null })
  performanceViewports.delete(`${accountId}:all`)
  void checkPerformance(accountId, 'all')
}

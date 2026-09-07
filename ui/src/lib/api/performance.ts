import { apiGet, apiSend } from '@/lib/api/client'
import type { AccountPerformance, PerformanceSettings } from '@/types/api'

export function getPerformance(id: number, range: '30' | '90' | 'all', signal?: AbortSignal, includeBacktest = true) {
  return apiGet<AccountPerformance>(`/account/performance/${id}?range=${range}&include_backtest=${includeBacktest}`, signal)
}

export function savePerformanceSettings(id: number, settings: PerformanceSettings) {
  return apiSend<PerformanceSettings>('PATCH', `/account/performance-settings/${id}`, settings)
}

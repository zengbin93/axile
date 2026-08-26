/** 系统 / 诊断类接口。 */
import { apiGet } from '@/lib/api/client'
import type {
  AlgorithmInfo,
  ChannelCapability,
  DirectoryListing,
} from '@/types/api'

export interface CalendarRequirement {
  calendar_id: string
  label: string
  channels: string[]
  channel_labels: string[]
  legacy_fallback_channels: string[]
  legacy_fallback_channel_labels: string[]
}

/** 探测后端存活。`GET /utils/health-check/` 返回裸 `true`。 */
export function healthCheck(signal?: AbortSignal): Promise<boolean> {
  return apiGet<boolean>('/utils/health-check/', signal)
}

/** 各交易渠道的依赖可用性（后端按本机是否装了依赖探测）。 */
export function getChannelCapabilities(signal?: AbortSignal): Promise<ChannelCapability[]> {
  return apiGet<ChannelCapability[]>('/capabilities/channels', signal)
}

export function getCalendarRequirements(signal?: AbortSignal): Promise<CalendarRequirement[]> {
  return apiGet<CalendarRequirement[]>('/capabilities/calendar-requirements', signal)
}

/** 已注册算法列表（内置 + 用户自定义）；渠道/槽位过滤在前端完成。 */
export function getAlgorithms(signal?: AbortSignal): Promise<AlgorithmInfo[]> {
  return apiGet<AlgorithmInfo[]>('/algorithms', signal)
}

export function getDirectories(path?: string, signal?: AbortSignal): Promise<DirectoryListing> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  return apiGet<DirectoryListing>(`/utils/directories${query}`, signal)
}

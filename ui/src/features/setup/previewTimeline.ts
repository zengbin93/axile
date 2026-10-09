import type { SchedulePreview } from '@/lib/api/accounts'
import type { ScheduleTimeRowTone } from '@/components/ui/ScheduleTimeRow'

export const PREVIEW_ROW_PITCH = 26
export const PREVIEW_MIN_ITEMS = 5
export const PREVIEW_MAX_ITEMS = 100
export const PREVIEW_PREFETCH_ROWS = 3

export interface SchedulePreviewItemPresentation {
  text: string
  tone: ScheduleTimeRowTone
}

/** 补发归入服务端标记的基础轮次；普通 cron 各自保留一行。 */
export function schedulePreviewRows(items: SchedulePreview['items']): SchedulePreview['items'] {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = item.base_scheduled_at ?? item.scheduled_at
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 将服务端日历决策收口为排程行的人读结果与颜色语义。 */
export function schedulePreviewItemPresentation(
  item: SchedulePreview['items'][number],
  reasonText: (reasonCode: string | null | undefined, fallback: string) => string,
  intervalMinutes?: number,
): SchedulePreviewItemPresentation {
  if (item.calendar_status === 'available_closed') {
    return { text: reasonText(item.reason_code, '休市').replace(/，已跳过$/, ''), tone: 'muted' }
  }
  if (item.calendar_status === 'unavailable') return { text: '日历不可用，按排程执行', tone: 'warning' }
  if (item.action === 'execute' && item.base_scheduled_at && intervalMinutes != null) {
    const index = item.index ?? 0
    const count = Math.max(0, (item.effective_count ?? 0) - Math.max(0, index - 1))
    const label = index > 0 ? '待补' : '补'
    return { text: `${label} ${count} 次${count > 0 ? ` · 隔 ${intervalMinutes} 分` : ''}`, tone: 'default' }
  }
  if (item.calendar_status === 'available_open') return { text: '交易日，执行', tone: 'default' }
  return { text: '按排程执行', tone: 'default' }
}

/** 后端按触发点分页，按每轮最多的触发数换算所需条数。 */
export function previewRequestLimit(rows: number, supplementCount: number): number {
  return Math.min(PREVIEW_MAX_ITEMS, rows * (supplementCount + 1))
}

/** 按列表可视高度计算首屏及后续批次条数。 */
export function previewLimitForHeight(height: number): number {
  if (!Number.isFinite(height) || height <= 0) return PREVIEW_MIN_ITEMS
  return Math.min(
    PREVIEW_MAX_ITEMS,
    Math.max(
      PREVIEW_MIN_ITEMS,
      Math.ceil(height / PREVIEW_ROW_PITCH) + PREVIEW_PREFETCH_ROWS,
    ),
  )
}

/** 续接未来时间线；边界去重且在游标未推进时停止自动续取。 */
export function appendSchedulePreview(
  current: SchedulePreview,
  next: SchedulePreview,
  requestedAfter: string,
): SchedulePreview {
  const seen = new Set(current.items.map((item) => item.scheduled_at))
  const appended = next.items.filter((item) => !seen.has(item.scheduled_at))
  const cursorAdvanced = next.next_cursor != null && next.next_cursor !== requestedAfter
  return {
    ...current,
    evaluated_at: next.evaluated_at,
    items: [...current.items, ...appended],
    next_cursor: next.next_cursor,
    has_more: next.has_more && cursorAdvanced && appended.length > 0,
  }
}

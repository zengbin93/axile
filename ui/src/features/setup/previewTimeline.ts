import type { SchedulePreview } from '@/lib/api/accounts'

export const PREVIEW_ROW_PITCH = 26
export const PREVIEW_MIN_ITEMS = 5
export const PREVIEW_MAX_ITEMS = 100
export const PREVIEW_PREFETCH_ROWS = 3

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

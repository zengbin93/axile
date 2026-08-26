import { describe, expect, test } from 'bun:test'
import type { SchedulePreview } from '@/lib/api/accounts'
import {
  appendSchedulePreview,
  PREVIEW_MAX_ITEMS,
  PREVIEW_MIN_ITEMS,
  previewLimitForHeight,
} from '@/features/setup/previewTimeline'

function preview(times: string[], nextCursor: string | null, hasMore: boolean): SchedulePreview {
  return {
    timezone: 'Asia/Shanghai',
    evaluated_at: '2026-08-26T15:00:00+08:00',
    calendar: {
      requirement: 'not_required',
      availability: 'not_required',
      unavailable_reason: null,
      calendar_id: null,
      label: null,
      coverage_start: null,
      coverage_end: null,
    },
    items: times.map((scheduledAt) => ({
      scheduled_at: scheduledAt,
      calendar_day: scheduledAt.slice(0, 10),
      calendar_status: 'not_required',
      action: 'execute',
      unavailable_reason: null,
      calendar_id: null,
      label: null,
      using_legacy_fallback: false,
      reason_code: null,
    })),
    next_cursor: nextCursor,
    has_more: hasMore,
  }
}

describe('previewLimitForHeight', () => {
  test('按可视高度计算并夹在后端安全范围内', () => {
    expect(previewLimitForHeight(0)).toBe(PREVIEW_MIN_ITEMS)
    expect(previewLimitForHeight(260)).toBe(13)
    expect(previewLimitForHeight(100_000)).toBe(PREVIEW_MAX_ITEMS)
  })
})

describe('appendSchedulePreview', () => {
  test('边界去重并续接推进后的游标', () => {
    const first = preview(['2026-08-27T15:00:00+08:00', '2026-08-27T15:01:00+08:00'], '2026-08-27T15:01:00+08:00', true)
    const next = preview(['2026-08-27T15:01:00+08:00', '2026-08-27T15:02:00+08:00'], '2026-08-27T15:02:00+08:00', true)
    const merged = appendSchedulePreview(first, next, '2026-08-27T15:01:00+08:00')
    expect(merged.items.map((item) => item.scheduled_at)).toEqual([
      '2026-08-27T15:00:00+08:00',
      '2026-08-27T15:01:00+08:00',
      '2026-08-27T15:02:00+08:00',
    ])
    expect(merged.has_more).toBe(true)
  })

  test('游标未推进或没有新条目时停止自动续取', () => {
    const cursor = '2026-08-27T15:01:00+08:00'
    const first = preview([cursor], cursor, true)
    const stalled = preview([cursor], cursor, true)
    expect(appendSchedulePreview(first, stalled, cursor).has_more).toBe(false)
  })
})

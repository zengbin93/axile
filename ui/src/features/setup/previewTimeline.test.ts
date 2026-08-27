import { describe, expect, test } from 'bun:test'
import type { SchedulePreview } from '@/lib/api/accounts'
import {
  appendSchedulePreview,
  PREVIEW_MAX_ITEMS,
  PREVIEW_MIN_ITEMS,
  previewLimitForHeight,
  schedulePreviewItemPresentation,
} from '@/features/setup/previewTimeline'
import { executionReasonText } from '@/features/account/executionReason'

function preview(times: string[], nextCursor: string | null, hasMore: boolean): SchedulePreview {
  return {
    timezone: 'Asia/Shanghai',
    evaluated_at: '2026-08-26T15:00:00+08:00',
    calendar: {
      requirement: 'required',
      availability: 'available',
      unavailable_reason: null,
      calendar_id: 'china',
      label: '中国交易日历',
      coverage_start: '2003-01-01',
      coverage_end: '2026-12-31',
    },
    items: times.map((scheduledAt) => ({
      scheduled_at: scheduledAt,
      calendar_day: scheduledAt.slice(0, 10),
      calendar_status: 'available_open',
      action: 'execute',
      unavailable_reason: null,
      calendar_id: 'china',
      label: '中国交易日历',
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

describe('schedulePreviewItemPresentation', () => {
  test('区分执行、跳过与日历降级的文案和颜色语义', () => {
    const base = preview(['2026-08-27T15:00:00+08:00'], null, false).items[0]!

    expect(schedulePreviewItemPresentation(base, executionReasonText)).toEqual({
      text: '交易日，执行',
      tone: 'default',
    })
    expect(schedulePreviewItemPresentation({
      ...base,
      calendar_status: 'available_closed',
      action: 'skip',
      reason_code: 'CALENDAR.NO_NIGHT_SESSION',
    }, executionReasonText)).toEqual({
      text: '无对应夜盘，已跳过',
      tone: 'muted',
    })
    expect(schedulePreviewItemPresentation({
      ...base,
      calendar_status: 'unavailable',
    }, executionReasonText)).toEqual({
      text: '日历不可用，按排程执行',
      tone: 'warning',
    })
  })
})

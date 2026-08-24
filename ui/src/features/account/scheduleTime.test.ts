import { describe, expect, it } from 'bun:test'

import { formatBeijingTimestamp, formatPlannedAt, formatRecentExecution, formatTimeUntil } from './scheduleTime'

const NOW = Date.parse('2026-08-24T09:30:00+08:00')

describe('formatRecentExecution', () => {
  it('formats just now, minutes, and hours', () => {
    expect(formatRecentExecution('2026-08-24T09:29:31+08:00', NOW)).toBe('刚刚')
    expect(formatRecentExecution('2026-08-24T09:12:00+08:00', NOW)).toBe('18 分钟前')
    expect(formatRecentExecution('2026-08-24T07:00:00+08:00', NOW)).toBe('2 小时前')
  })

  it('formats yesterday and older dates across years', () => {
    expect(formatRecentExecution('2026-08-23T08:00:00+08:00', NOW)).toBe('昨天 08:00')
    expect(formatRecentExecution('2025-12-31T23:00:00+08:00', NOW)).toBe('2025 年 12 月 31 日 23:00')
  })
})

describe('future schedule formatting', () => {
  it('pairs natural dates with relative time', () => {
    expect(formatPlannedAt('2026-08-24T09:48:00+08:00', NOW)).toBe('今天 09:48')
    expect(formatTimeUntil('2026-08-24T09:48:00+08:00', NOW)).toBe('18 分钟后')
    expect(formatPlannedAt('2026-08-25T15:00:00+08:00', NOW)).toBe('明天 15:00')
    expect(formatTimeUntil('2026-08-24T11:01:00+08:00', NOW)).toBe('2 小时后')
  })

  it('shows the year when a plan crosses into another year', () => {
    const yearEnd = Date.parse('2026-12-31T23:30:00+08:00')
    expect(formatPlannedAt('2027-01-01T10:00:00+08:00', yearEnd)).toBe('明天 10:00')
    expect(formatPlannedAt('2027-01-02T10:00:00+08:00', yearEnd)).toBe('2027 年 1 月 2 日 10:00')
  })

  it('provides a precise Beijing timestamp for hover text', () => {
    expect(formatBeijingTimestamp('2026-08-24T01:48:00Z')).toBe('2026-08-24 09:48:00（北京时间）')
  })
})

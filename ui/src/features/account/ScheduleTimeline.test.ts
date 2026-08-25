import { describe, expect, it } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ScheduleSummary, ScheduleTimeline } from './ScheduleTimeline'

const NOW = Date.parse('2026-08-24T09:30:00+08:00')

function render(lastExecutedAt: string | null, nextRunTimes: string[]): string {
  return renderToStaticMarkup(createElement(ScheduleTimeline, { lastExecutedAt, nextRunTimes, now: NOW }))
}

describe('ScheduleTimeline', () => {
  it('renders the recent execution and at most three future plans', () => {
    const html = render('2026-08-24T07:00:00+08:00', [
      '2026-08-24T10:00:00+08:00',
      '2026-08-24T11:00:00+08:00',
      '2026-08-25T10:00:00+08:00',
      '2026-08-26T10:00:00+08:00',
    ])

    expect(html).toContain('最近一次执行')
    expect(html).toContain('2 小时前')
    expect(html).toContain('今天 10:00')
    expect(html).toContain('明天 10:00')
    expect(html).not.toContain('8 月 26 日')
  })

  it('renders fewer future plans without placeholders', () => {
    const html = render(null, ['2026-08-24T10:00:00+08:00'])

    expect(html).toContain('尚无执行')
    expect(html).toContain('今天 10:00')
    expect(html).not.toContain('暂无自动执行计划')
  })

  it('renders explicit empty states', () => {
    const html = render(null, [])

    expect(html).toContain('尚无执行')
    expect(html).toContain('暂无自动执行计划')
  })

  it('reflects refreshed schedule props', () => {
    const before = render(null, [])
    const after = render(null, ['2026-08-24T10:00:00+08:00'])

    expect(before).toContain('暂无自动执行计划')
    expect(after).toContain('今天 10:00')
  })
})

describe('ScheduleSummary', () => {
  it('uses the same relative and natural time language as the timeline', () => {
    const html = renderToStaticMarkup(
      createElement(ScheduleSummary, {
        lastExecutedAt: '2026-08-24T07:00:00+08:00',
        nextRunAt: '2026-08-24T10:00:00+08:00',
        now: NOW,
      }),
    )

    expect(html).toContain('上次 2 小时前')
    expect(html).toContain('下次 今天 10:00')
    expect(html).toContain('2026-08-24 07:00:00（北京时间）')
    expect(html).not.toContain('下次排程')
  })

  it('omits the next-run segment when no execution is scheduled', () => {
    const html = renderToStaticMarkup(
      createElement(ScheduleSummary, { lastExecutedAt: null, nextRunAt: null, now: NOW }),
    )

    expect(html).toContain('尚无执行')
    expect(html).not.toContain('下次')
  })
})

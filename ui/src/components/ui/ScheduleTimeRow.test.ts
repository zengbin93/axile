import { describe, expect, it } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ScheduleTimeRow } from './ScheduleTimeRow'

const NOW = Date.parse('2026-08-27T09:00:00+08:00')

describe('ScheduleTimeRow', () => {
  it('renders a natural date with an exact Beijing timestamp', () => {
    const html = renderToStaticMarkup(createElement(ScheduleTimeRow, {
      scheduledAt: '2026-08-27T15:00:00+08:00',
      trailing: '6 小时后',
      now: NOW,
      tone: 'muted',
      size: 'md',
    }))

    expect(html).toContain('今天 15:00')
    expect(html).toContain('6 小时后')
    expect(html).toContain('2026-08-27 15:00:00（北京时间）')
    expect(html).toContain('text-ink-3')
    expect(html).toContain('text-[15px]')
  })

  it('uses warning color without changing the schedule time color', () => {
    const html = renderToStaticMarkup(createElement(ScheduleTimeRow, {
      scheduledAt: '2026-08-28T15:00:00+08:00',
      trailing: '日历不可用，按排程执行',
      now: NOW,
      tone: 'warning',
    }))

    expect(html).toContain('明天 15:00')
    expect(html).toContain('text-warn')
    expect(html).toContain('font-medium text-ink-1')
  })
})

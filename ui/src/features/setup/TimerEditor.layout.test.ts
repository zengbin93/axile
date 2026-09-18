import { expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { TimerEditor } from '@/features/setup/TimerEditor'
import { defaultTimerEditorState } from '@/features/setup/cron'

function renderPage(leading?: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(
    createElement(TimerEditor, {
      tradeChannel: 'ctp',
      scheduleKind: 'cn_futures',
      value: defaultTimerEditorState('cn_futures'),
      layout: 'page',
      leading,
      onChange: () => {},
    }),
  )
}

test('page 布局把 leading 放进左列，预览仍是同一网格的右列', () => {
  const html = renderPage(createElement('h1', null, '定时任务 · TQ'))
  expect(html).toContain('定时任务 · TQ')
  expect(html).toContain('排程预览')
  expect(html.indexOf('定时任务 · TQ')).toBeLessThan(html.indexOf('排程预览'))
  expect(html.indexOf('定时任务 · TQ')).toBeLessThan(html.indexOf('自动调仓'))
  expect(html).toContain('min-[1120px]:grid-cols-[minmax(0,1fr)_300px]')
})

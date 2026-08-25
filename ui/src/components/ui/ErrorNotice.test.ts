import { describe, expect, it } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ErrorNotice } from './ErrorNotice'

describe('ErrorNotice', () => {
  it('renders a stable open error slot with a retry action', () => {
    const html = renderToStaticMarkup(createElement(ErrorNotice, {
      title: '自动执行计划加载失败', error: new Error('CTP 交易前置断线'),
      variant: 'section', onRetry: () => {},
    }))
    expect(html).toContain('grid-rows-[1fr]')
    expect(html).toContain('CTP 交易前置断线')
    expect(html).toContain('重试：自动执行计划加载失败')
    expect(html).toContain('text-warn')
    expect(html).not.toContain('text-bad')
  })

  it('keeps a collapsed inert slot when there is no error', () => {
    const html = renderToStaticMarkup(createElement(ErrorNotice, { title: '加载失败', error: null }))
    expect(html).toContain('grid-rows-[0fr]')
    expect(html).toContain('inert=""')
  })
})

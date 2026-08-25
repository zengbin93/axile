import { describe, expect, it } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'

import { Breadcrumb } from './Breadcrumb'

function renderBreadcrumb(trail: Parameters<typeof Breadcrumb>[0]['trail']): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(Breadcrumb, { trail })),
  )
}

describe('Breadcrumb', () => {
  it('renders an ancestor annotation inside the same link', () => {
    const html = renderBreadcrumb([
      { label: 'test', to: '/accounts/1', annotation: 'CTP' },
      { label: '持仓明细' },
    ])

    expect(html).toContain('<a')
    expect(html).toContain(
      '<span>test</span><span class="ml-1 text-[11px] text-ink-3/70 group-hover:text-ink-2">· CTP</span>',
    )
    expect(html.indexOf('test')).toBeLessThan(html.indexOf('</a>', html.indexOf('test')))
    expect(html.indexOf('CTP')).toBeLessThan(html.indexOf('</a>', html.indexOf('CTP')))
  })

  it('does not render an annotation on the current crumb', () => {
    const html = renderBreadcrumb([{ label: 'test', annotation: 'CTP' }])

    expect(html).toContain('aria-current="page"')
    expect(html).not.toContain('CTP')
  })
})

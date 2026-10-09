import { expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SupplementControls } from '@/features/setup/SupplementControls'

function render(count: number, minutes: number) {
  return renderToStaticMarkup(createElement(SupplementControls, {
    supN: count, supM: minutes, onN: () => {}, onM: () => {},
  }))
}

test('不补时收起间隔，禁用交互并保留原间隔值', () => {
  const html = render(0, 3)
  expect(html).toContain('不补')
  expect(html).toContain('inert=""')
  expect(html).toContain('grid-rows-[0fr]')
  expect(html).toContain('aria-valuetext="3 分" aria-disabled="true"')
  expect(html).toContain('tabindex="-1"')
})

test('已有配置超出快捷档位时仍显示原值，步进不静默重写配置', () => {
  const html = render(6, 10)
  expect(html).toContain('aria-valuenow="6"')
  expect(html).toContain('aria-valuetext="6 次"')
  expect(html).toContain('aria-valuenow="10"')
  expect(html).toContain('aria-valuetext="10 分"')
  expect(html).toContain('grid-rows-[1fr]')
  expect(html).not.toContain('inert=""')
})

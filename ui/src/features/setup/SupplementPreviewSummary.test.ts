import { expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SupplementPreviewSummary } from '@/features/setup/SupplementPreviewSummary'

test('补发摘要保留可访问的完整文案，首帧不播放换字动画', () => {
  const html = renderToStaticMarkup(createElement(SupplementPreviewSummary, {
    value: { enabled: true, count: 2, interval: 1 }, fallback: '交易日，执行',
  }))
  expect(html).toContain('aria-label="补 2 次 · 隔 1 分"')
  expect(html).not.toContain('ink-rewrite-in')
})

test('补发关闭时显示不补发；裁剪为零时保留补发零次的区别', () => {
  const off = renderToStaticMarkup(createElement(SupplementPreviewSummary, {
    value: { enabled: false, count: 0, interval: 1 }, fallback: '交易日，执行',
  }))
  expect(off).toContain('aria-label="不补发"')
  const clipped = renderToStaticMarkup(createElement(SupplementPreviewSummary, {
    value: { enabled: true, count: 0, interval: 1 }, fallback: '交易日，执行',
  }))
  expect(clipped).toContain('aria-label="补 0 次"')
})

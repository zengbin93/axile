import { expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SupplementPreviewSummary } from '@/features/setup/SupplementPreviewSummary'

function render(count: number, configuredCount: number) {
  return renderToStaticMarkup(createElement(SupplementPreviewSummary, { value: { count, configuredCount } }))
}

test('正常轮次和未设置补发的轮次不显示重复说明', () => {
  expect(render(2, 2)).not.toContain('<span aria-label=')
  expect(render(0, 0)).not.toContain('<span aria-label=')
  expect(renderToStaticMarkup(createElement(SupplementPreviewSummary))).toBe('')
})

test('仅提示补发裁剪，首帧不播放换字动画', () => {
  const clipped = render(1, 2)
  expect(clipped).toContain('aria-label="仅补 1 次"')
  expect(clipped).not.toContain('ink-rewrite-in')
  expect(render(0, 2)).toContain('aria-label="无补发"')
})

import { expect, test } from 'bun:test'
import { sliderValueAt } from './sliderValue'

test('滑条按最小值起算刻度，保留小数精度且拖出轨道仍受边界限制', () => {
  expect(sliderValueAt(-0.2, 0.01, 100, 0.01)).toBe(0.01)
  expect(sliderValueAt(1.2, 0.01, 100, 0.01)).toBe(100)
  expect(sliderValueAt(0.2, 0, 1, 0.1)).toBe(0.2)
  expect(sliderValueAt(0.26, 0, 1, 0.1)).toBe(0.3)
  expect(sliderValueAt(1, 0, 1, 0.3)).toBe(1)
})

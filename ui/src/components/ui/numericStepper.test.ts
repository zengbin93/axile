import { describe, expect, it } from 'bun:test'
import { stepNumericValue } from './numericStepper'

describe('stepNumericValue', () => {
  const opts = { step: 10, min: 0, max: 500 }

  it('按步长增减', () => {
    expect(stepNumericValue('100', 1, opts)).toBe('110')
    expect(stepNumericValue('100', -1, opts)).toBe('90')
  })

  it('夹在区间内', () => {
    expect(stepNumericValue('0', -1, opts)).toBe('0')
    expect(stepNumericValue('5', -1, opts)).toBe('0')
    expect(stepNumericValue('495', 1, opts)).toBe('500')
    expect(stepNumericValue('500', 1, opts)).toBe('500')
  })

  it('max 缺省 = 无上限', () => {
    expect(stepNumericValue('999999', 1, { step: 1, min: 0 })).toBe('1000000')
  })

  it('非法或空草稿原样返回（步进按钮因此禁用）', () => {
    expect(stepNumericValue('', 1, opts)).toBe('')
    expect(stepNumericValue('abc', 1, opts)).toBe('abc')
    expect(stepNumericValue('1.5', 1, opts)).toBe('1.5')
  })
})

it('小数步进保持精度，默认整数调用仍拒绝小数', () => {
  const opts = { step: 0.1, decimal: true }
  expect(stepNumericValue('0.2', 1, opts)).toBe('0.3')
  expect(stepNumericValue('0.3', -1, opts)).toBe('0.2')
  expect(stepNumericValue('-0.2', -1, opts)).toBe('-0.3')
  expect(stepNumericValue('1.23456', 1, { step: 0.01, decimal: true })).toBe('1.24456')
  expect(stepNumericValue('0.2', 1, { step: 1 })).toBe('0.2')
  expect(stepNumericValue('Infinity', 1, opts)).toBe('Infinity')
  expect(stepNumericValue('0.3', 1, { ...opts, max: 0.35 })).toBe('0.35')
})

it('排他边界阻止越界，不缩窄合法小数范围', () => {
  const opts = { step: 1, min: 0, max: 100, decimal: true, exclusiveMin: true }
  expect(stepNumericValue('0.5', 1, opts)).toBe('1.5')
  expect(stepNumericValue('0.5', -1, opts)).toBe('0.5')
  expect(stepNumericValue('1', -1, opts)).toBe('1')
  expect(stepNumericValue('12.3456', 1, opts)).toBe('13.3456')
  expect(stepNumericValue('99.5', 1, opts)).toBe('100')
})

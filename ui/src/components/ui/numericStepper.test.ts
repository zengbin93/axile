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

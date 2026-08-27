import { describe, expect, it } from 'bun:test'

import { formatLeverage, leverageError, leverageValue, stepLeverage } from './leverage'

describe('leverageError', () => {
  it('接受渠道范围内的合法步进', () => {
    expect(leverageError('0')).toBeNull()
    expect(leverageError('3.0')).toBeNull()
    expect(leverageError('5', { max: 5, step: 0.5 })).toBeNull()
  })

  it('拒绝空值、负数、越界和小于 0.1 的步进', () => {
    expect(leverageError('')).toBe('请输入杠杆')
    expect(leverageError('-0.1')).toBe('需为非负数')
    expect(leverageError('5.5', { max: 5, step: 0.5 })).toContain('≤ 5')
    expect(leverageError('3.05')).toBe('最小步进为 0.1')
  })

  it('编辑页可把空值解释为不修改', () => {
    expect(leverageError('', { allowEmpty: true })).toBeNull()
  })
})

describe('leverageValue', () => {
  it('只解析满足范围和精度约束的值', () => {
    expect(leverageValue('3.1')).toBe(3.1)
    expect(leverageValue('')).toBeNull()
    expect(leverageValue('3.14')).toBeNull()
  })
})

describe('stepLeverage', () => {
  it('使用十分位运算按 0.1 调整', () => {
    expect(stepLeverage('3.0', 1)).toBe('3.1')
    expect(stepLeverage('3.0', -1)).toBe('2.9')
    expect(stepLeverage('0.2', 1)).toBe('0.3')
  })

  it('可按指定增量快速调整', () => {
    expect(stepLeverage('3.0', 1, undefined, 1)).toBe('4.0')
    expect(stepLeverage('3.0', -1, undefined, 1)).toBe('2.0')
    expect(stepLeverage('3.5', 1, { max: 5, step: 0.5 }, 1)).toBe('4.5')
  })

  it('夹在运行时渠道边界内', () => {
    expect(stepLeverage('0.0', -1)).toBe('0.0')
    expect(stepLeverage('5.0', 1, { max: 5, step: 0.5 })).toBe('5.0')
    expect(stepLeverage('0.5', -1, { min: 0, max: 5, step: 0.5 }, 1)).toBe('0.0')
  })

  it('非法输入保持原值', () => {
    expect(stepLeverage('', 1)).toBe('')
    expect(stepLeverage('-1', 1)).toBe('-1')
    expect(stepLeverage('3.05', 1)).toBe('3.05')
  })
})

describe('formatLeverage', () => {
  it('统一为一位小数', () => {
    expect(formatLeverage(0)).toBe('0.0')
    expect(formatLeverage(3)).toBe('3.0')
    expect(formatLeverage(3.1)).toBe('3.1')
  })
})

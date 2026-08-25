import { describe, expect, test } from 'bun:test'

import {
  stepWeightPrecision,
  weightPrecisionError,
  weightPrecisionPercent,
} from '@/features/account/weightPrecision'

describe('weightPrecisionError', () => {
  test('只接受 10 的非正整数次幂', () => {
    expect(weightPrecisionError('1')).toBeNull()
    expect(weightPrecisionError('0.01')).toBeNull()
    expect(weightPrecisionError('0.02')).not.toBeNull()
    expect(weightPrecisionError('10')).not.toBeNull()
    expect(weightPrecisionError('0')).not.toBeNull()
  })

  test('可允许空值表示不修改', () => {
    expect(weightPrecisionError('', { allowEmpty: true })).toBeNull()
  })
})

test('权重精度按十倍数量级调整', () => {
  expect(stepWeightPrecision('0.01', -1)).toBe('0.001')
  expect(stepWeightPrecision('0.01', 1)).toBe('0.1')
  expect(stepWeightPrecision('1', 1)).toBe('1')
  expect(stepWeightPrecision('0.02', -1)).toBe('0.02')
})

test('权重精度转换为百分比说明', () => {
  expect(weightPrecisionPercent('0.01')).toBe('1%')
  expect(weightPrecisionPercent('0.001')).toBe('0.1%')
  expect(weightPrecisionPercent('oops')).toBeNull()
})

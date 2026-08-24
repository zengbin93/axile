import { expect, test } from 'bun:test'

import { displayCurrencyUnit, withCurrency } from './format'

test('人民币币种代码显示为元', () => {
  expect(displayCurrencyUnit('CNY')).toBe('元')
  expect(displayCurrencyUnit(' cny ')).toBe('元')
  expect(displayCurrencyUnit('USDQ')).toBe('USDQ')
  expect(displayCurrencyUnit(null)).toBe('')
})

test('withCurrency preserves public and plugin currency formatting', () => {
  expect(withCurrency('100.00', 'CNY')).toBe('¥100.00')
  expect(withCurrency('100.00', 'USDQ')).toBe('100.00U')
  expect(withCurrency('100.00', 'EUR')).toBe('100.00 EUR')
})

import { expect, test } from 'bun:test'

import { withCurrency } from './format'

test('withCurrency preserves public and plugin currency formatting', () => {
  expect(withCurrency('100.00', 'CNY')).toBe('¥100.00')
  expect(withCurrency('100.00', 'USDQ')).toBe('100.00U')
  expect(withCurrency('100.00', 'EUR')).toBe('100.00 EUR')
})

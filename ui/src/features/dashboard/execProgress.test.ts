import { expect, test } from 'bun:test'
import { isBusyStatus, isExecutingStatus, phaseLabel } from './execProgress'

test('queued 不误标成下单', () => {
  expect(phaseLabel('queued')).toBe('等待开跑')
  expect(phaseLabel('executing')).toBe('下单')
})

test('queued 是忙但不是正在下单', () => {
  expect(isBusyStatus('queued')).toBe(true)
  expect(isExecutingStatus('queued')).toBe(false)
  expect(isExecutingStatus('running')).toBe(true)
})
